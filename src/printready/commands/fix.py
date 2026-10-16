"""`printready fix ART --size 3 [--mode rules|agent]`: check, fix, cut line, proof, report.

Rules mode runs offline; with --model it also runs the vision text check. Agent mode needs
printready.agent.run_agent and printready.llm.make_client (chunk K4).
Exit 0 for ready/fixable, 1 for needs_person, 2 for a usage, profile or setup error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from printready.commands import positive_float
from printready.profile import ProfileError, load_profile
from printready.types import RunResult, Spec

OUTCOME_LABELS = {"ready": "READY", "fixable": "FIXABLE", "needs_person": "NEEDS A PERSON"}


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "fix",
        help="fix artwork and write proof, cut line and report",
        description="Check and fix one image, then write the per-image outputs to OUT/<name>/.",
    )
    p.add_argument("art", metavar="ART", type=Path, help="artwork file (PNG, JPG or WebP)")
    p.add_argument(
        "--size", type=positive_float, required=True,
        help="longest side of the finished sticker in inches, border included",
    )
    p.add_argument("--profile", type=Path, default=None, help="profile YAML (default: shipped die-cut profile)")
    p.add_argument("--mode", choices=("rules", "agent"), default="rules", help="fixed rules or tool-use agent")
    p.add_argument(
        "--model", default=None,
        help="vision/agent model, e.g. xai:grok-4.3 (rules mode runs the vision check only if given)",
    )
    p.add_argument("--prompt", default=None, help="the prompt the art was generated from, if known")
    p.add_argument("--out", type=Path, default=Path("out"), help="output root; files go to OUT/<name>/ (default: out)")
    p.add_argument("--env-file", type=Path, default=None, help="dotenv file to load API keys from")
    p.set_defaults(func=run)


def _client(model: str, env_file: Path | None):
    """Build an LLM client lazily (K4 code); raises on any setup problem."""
    from printready import llm

    if env_file is not None:
        llm.load_env_file(env_file)
    return llm.make_client(model)


def _default_model() -> str:
    from printready import llm

    return getattr(llm, "DEFAULT_MODEL", "xai:grok-4.3")


def summarize(run: RunResult, out_dir: Path) -> str:
    lines = [f"{OUTCOME_LABELS[run.outcome]}  ({run.mode} mode, {run.elapsed_s:.1f} s, ${run.cost_usd:.4f})"]
    before = {f.check: f for f in run.before.findings}
    for f in run.after.findings:
        b = before.get(f.check)
        if b is None or b.status != f.status or f.status in ("warn", "fail"):
            arrow = f"{b.status} -> {f.status}" if b is not None else f"new {f.status}"
            lines.append(f"  {f.check:<12} {arrow:<14} {f.message}")
    for s in run.art.history if run.art is not None else []:
        state = "reverted" if s.damaged else ("applied" if s.ok else "refused")
        guard = f" [{s.guard['label']}: {s.guard['value']:g}, limit {s.guard['limit']:g}]" if s.guard else ""
        lines.append(f"  step {s.fix:<18} {state:<9}{guard}")
    lines.append(f"customer: {run.customer_message}")
    for note in run.person_notes:
        lines.append(f"person:   {note}")
    lines.append(f"outputs:  {out_dir} ({', '.join(sorted(run.outputs.values()))})")
    return "\n".join(lines)


def run(args: argparse.Namespace) -> int:
    try:
        profile = load_profile(args.profile)
        spec = Spec("die_cut", args.size, prompt=args.prompt)
        if spec.size_in <= 2 * profile.border_in:
            raise ValueError(f"a {spec.size_in:g} in sticker leaves no room inside a {profile.border_in:g} in border")
    except (ProfileError, ValueError) as exc:
        print(f"fix: {exc}", file=sys.stderr)
        return 2
    out_dir = args.out / args.art.stem

    if args.mode == "rules":
        from printready.pipeline import run_rules

        client = None
        if args.model:
            try:
                client = _client(args.model, args.env_file)
            except Exception as exc:  # noqa: BLE001 - setup errors are reported, not raised
                print(f"fix: cannot set up model {args.model}: {exc}", file=sys.stderr)
                return 2
        result = run_rules(args.art, spec, profile, out_dir, client=client)
    else:
        model = args.model or _default_model()
        try:
            from printready.agent import run_agent

            client = _client(model, args.env_file)
            result = run_agent(args.art, spec, profile, out_dir, client)
        except NotImplementedError:
            print("fix --mode agent: not implemented yet (chunk K4)", file=sys.stderr)
            return 2
        except (ImportError, OSError, KeyError, ValueError, RuntimeError) as exc:
            print(f"fix --mode agent: cannot run with {model}: {exc}", file=sys.stderr)
            return 2

    print(f"{args.art.name} as a {spec.size_in:g} in die-cut sticker")
    print(summarize(result, out_dir))
    return 1 if result.outcome == "needs_person" else 0
