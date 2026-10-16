"""`printready realset gen | run | label | eval | sheet`: the real Grok image set (chunk K5).

    realset gen   --split dev|test [--models a,b]         images through the spend guard (resumable)
    realset run   --split S --mode rules|agent [--model M] [--sample-50] [--only IDS] [--yes] [--force]
    realset label --split S --pass 1|2                    the workbench in label mode
    realset eval  --split S [--with-rerun]                eval.md + summary.json, PREREG verdict
    realset rerun-list --split S --deadline T             runs that never reached a model (PREREG addendum 1)
    realset rerun --split S --mode M --yes                re-attempt only those, into results/realset/S-rerun/
    realset sheet --split S [--mode rules]                contact sheet for looking at results
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from printready.commands import positive_int
from printready.realset import IMAGE_MODELS, MODES, SPLITS, Paths


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "realset",
        help="real generated images: generate, run, label, evaluate",
        description="Generate real images from prompts, run both modes, label them by keypress, evaluate.",
    )
    actions = p.add_subparsers(dest="realset_action", metavar="ACTION", required=True)

    def split_arg(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--split", choices=SPLITS, required=True)

    gen = actions.add_parser("gen", help="generate one image per prompt per image model")
    split_arg(gen)
    gen.add_argument("--models", default=",".join(IMAGE_MODELS), help="comma-separated image models")
    gen.add_argument("--env-file", type=Path, default=None, help="dotenv file to load API keys from")
    gen.set_defaults(func=run_gen)

    runp = actions.add_parser("run", help="run rules or agent mode over a split (3 in die-cut)")
    split_arg(runp)
    runp.add_argument("--mode", choices=MODES, required=True)
    runp.add_argument("--model", default=None,
                      help="agent model (default llm.DEFAULT_MODEL); in rules mode, the vision model (none: no vision)")
    runp.add_argument("--sample-50", action="store_true", help="only the seeded 50-image labelling sample")
    runp.add_argument("--limit", type=positive_int, default=None, help="at most this many images (smoke runs)")
    runp.add_argument("--yes", action="store_true", help="confirm a paid agent run after reading the estimate")
    runp.add_argument("--only", default=None, help="comma-separated prompt ids or sha256 prefixes, e.g. d01,d07")
    runp.add_argument("--force", action="store_true",
                      help="re-run images already done (never agent mode on the test split: PREREG 5)")
    runp.add_argument("--env-file", type=Path, default=None, help="dotenv file to load API keys from")
    runp.set_defaults(func=run_run)

    label = actions.add_parser("label", help="label images by keypress (local page, blind)")
    split_arg(label)
    label.add_argument("--pass", dest="label_pass", type=int, choices=(1, 2), required=True)
    label.add_argument("--port", type=positive_int, default=None)
    label.add_argument("--no-open", action="store_true", help="do not open a browser")
    label.set_defaults(func=run_label)

    ev = actions.add_parser("eval", help="agreement tables and the keep-or-remove verdict")
    split_arg(ev)
    ev.add_argument("--with-rerun", action="store_true", help="also the numbers with the PREREG addendum 1 reruns")
    ev.set_defaults(func=run_eval)

    rl = actions.add_parser("rerun-list", help="list runs whose every model call got HTTP 403/429 with zero tokens")
    split_arg(rl)
    rl.add_argument("--deadline", required=True, help="after this time unsettled reruns become hand-off 'error', "
                                                      "e.g. 2026-10-19T18:00+05:30")
    rl.set_defaults(func=run_rerun_list)

    rr = actions.add_parser("rerun", help="re-attempt only the listed runs (PREREG addendum 1)")
    split_arg(rr)
    rr.add_argument("--mode", choices=MODES, required=True)
    rr.add_argument("--yes", action="store_true", help="make the paid calls after reading the estimate")
    rr.add_argument("--env-file", type=Path, default=None, help="dotenv file to load API keys from")
    rr.set_defaults(func=run_rerun)

    sheet = actions.add_parser("sheet", help="contact sheet: original | proof | outcome per image")
    split_arg(sheet)
    sheet.add_argument("--mode", choices=MODES, default="rules")
    sheet.add_argument("--compare", action="store_true", help="original | rules proof | agent proof per image")
    sheet.set_defaults(func=run_sheet)


def _ledger_line() -> str:
    from printready import spend

    return f"ledger ${spend.ledger_total():.4f} of ${spend.cap_usd():.2f} cap"


def _load_env(env_file: Path | None) -> None:
    from printready import llm

    if env_file is not None and not env_file.exists():
        raise SystemExit(f"realset: --env-file {env_file} does not exist")
    path = env_file or llm.default_env_file()
    if env_file is not None or path.exists():
        llm.load_env_file(path)


def _prereg_gate(split: str) -> bool:
    """Anything that touches the test split needs a verified, committed PREREG.md (printready.prereg)."""
    if split != "test":
        return True
    from printready import prereg

    try:
        prereg.require_verified()
    except prereg.PreregError as exc:
        print(f"realset: refused for the test split: {exc}", file=sys.stderr)
        return False
    return True


def run_gen(args: argparse.Namespace) -> int:
    from printready.realset.gen import generate
    from printready.spend import BudgetExceeded, price_for

    paths = Paths.for_split(args.split)
    if not _prereg_gate(args.split):
        return 1
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    _load_env(args.env_file)
    from printready.llm import make_client
    from printready.realset import ID_PREFIX, load_prompts

    n = len(load_prompts(paths.prompts, ID_PREFIX[args.split]))
    print(f"realset gen {args.split}: {n} prompts x {len(models)} models, up to "
          f"${n * sum(price_for(m).per_image for m in models):.2f}; {_ledger_line()}")
    try:
        new = generate(paths, models, client_factory=lambda m: make_client(m, env_file=args.env_file))
    except BudgetExceeded as exc:
        print(f"realset gen: stopped, {exc}", file=sys.stderr)
        return 1
    print(f"generated {len(new)} images (${sum(e['cost_usd'] for e in new):.2f}); {_ledger_line()}")
    return 0


def run_run(args: argparse.Namespace) -> int:
    from printready.realset.runs import agent_estimate, may_rerun, pass1_missing, run_split, select

    paths = Paths.for_split(args.split)
    if not _prereg_gate(args.split):
        return 1
    if args.split == "test" and (missing := pass1_missing(paths)):
        print(f"realset run --split test: refused, {len(missing)} sampled images still need a pass-1 label "
              "(blinding: no tool output before pass 1).", file=sys.stderr)
        return 2
    if args.force and not may_rerun(args.split, args.mode):
        print("realset run: agent mode never re-runs a test image (PREREG 5).", file=sys.stderr)
        return 2
    only = [o.strip() for o in args.only.split(",") if o.strip()] if args.only else None
    items = select(paths, args.sample_50, only)[: args.limit]
    if not items:
        print(f"realset run: no images in {paths.manifest}; run `realset gen --split {args.split}` first.", file=sys.stderr)
        return 2
    factory = None
    from printready.llm import DEFAULT_MODEL

    model = args.model or (DEFAULT_MODEL if args.mode == "agent" else None)
    if model:
        _load_env(args.env_file)
        from printready.llm import make_client

        try:
            make_client(model, env_file=args.env_file).close()  # fail fast: key, provider, price
        except Exception as exc:  # noqa: BLE001 - setup problems are reported, not raised
            print(f"realset run: cannot use {model}: {exc}", file=sys.stderr)
            return 2
        factory = lambda: make_client(model, env_file=args.env_file)  # noqa: E731 - one client per image
    if args.mode == "agent":
        typical, worst = agent_estimate(model, len(items))
        print(f"agent mode on {len(items)} images with {model}: about ${typical:.2f}, at most ${worst:.2f}; "
              f"{_ledger_line()}")
        if not args.yes:
            print("Re-run with --yes to start.", file=sys.stderr)
            return 2
    from printready.spend import BudgetExceeded

    try:
        rows = run_split(paths, args.mode, items, client_factory=factory, force=args.force)
    except BudgetExceeded as exc:
        print(f"realset run: stopped, {exc}", file=sys.stderr)
        return 1
    counts = {o: sum(r["outcome"] == o for r in rows) for o in ("ready", "fixable", "needs_person")}
    print(f"{args.mode}: {len(rows)} images run, " + ", ".join(f"{o} {n}" for o, n in counts.items())
          + f"; cost ${sum(r['cost_usd'] for r in rows):.4f}; {_ledger_line()}")
    print(f"summaries: {paths.runs(args.mode)}")
    return 0


def run_label(args: argparse.Namespace) -> int:
    from printready.realset.label import pass1_items, pass2_items, serve_labels
    from printready.realset.runs import pass1_missing

    paths = Paths.for_split(args.split)
    if args.label_pass == 1:
        data = pass1_items(paths)
    else:
        if pass1_missing(paths):
            print("realset label --pass 2: finish pass 1 first.", file=sys.stderr)
            return 2
        data = pass2_items(paths)
    print(f"label pass {args.label_pass}: {len(data['items'])} images; labels go to {paths.labels}")
    return serve_labels(paths, args.label_pass, open_browser=not args.no_open, port=args.port)


def run_eval(args: argparse.Namespace) -> int:
    from printready.realset.evaluate import evaluate

    paths = Paths.for_split(args.split)
    summary = evaluate(paths, with_rerun=args.with_rerun)
    print((paths.results / "eval.md").read_text(encoding="utf-8"))
    print(f"wrote {paths.results / 'eval.md'} and {paths.results / 'summary.json'} (verdict {summary['verdict']['status']})")
    return 0


def run_sheet(args: argparse.Namespace) -> int:
    from printready.realset.sheet import compare_sheet, contact_sheet

    paths = Paths.for_split(args.split)
    out = compare_sheet(paths) if args.compare else contact_sheet(paths, args.mode)
    print(f"wrote {out}")
    return 0


def run_rerun_list(args: argparse.Namespace) -> int:
    from printready.realset import last_by, read_jsonl
    from printready.realset.rerun import LIST_NAME, RerunError, write_list

    paths = Paths.for_split(args.split)
    try:
        listed = write_list(paths, args.deadline)
    except RerunError as exc:
        print(f"realset rerun-list: {exc}", file=sys.stderr)
        return 2
    for mode in MODES:
        total = len(last_by(read_jsonl(paths.runs(mode)), "image"))
        print(f"{mode}: {len(listed[mode])} of {total} runs never reached a model (every call HTTP 403/429, 0 tokens)")
    print(f"wrote {paths.results / LIST_NAME} (deadline {args.deadline}); runs that billed any token are never listed")
    return 0


def run_rerun(args: argparse.Namespace) -> int:
    from printready.llm import make_client
    from printready.realset.rerun import RerunError, read_list, rerun, rerun_runs, status
    from printready.realset.runs import agent_estimate
    from printready.spend import BudgetExceeded, estimate, price_for

    paths = Paths.for_split(args.split)
    if not _prereg_gate(args.split):
        return 1
    try:
        deadline, _ = read_list(paths)
        state = status(paths, args.mode)
    except RerunError as exc:
        print(f"realset rerun: {exc}", file=sys.stderr)
        return 2
    pending = state["pending"]
    print(f"{args.mode}: {len(state['settled'])} settled, {len(state['final'])} final at the deadline, "
          f"{len(pending)} to attempt; deadline {deadline.isoformat()}")
    if pending:
        _load_env(args.env_file)
        from printready.llm import DEFAULT_MODEL

        if args.mode == "agent":
            typical, worst = agent_estimate(DEFAULT_MODEL, len(pending))
        else:
            per_call = estimate(price_for(DEFAULT_MODEL), tokens_in=3000, tokens_out=4096)
            typical, worst = 0.004 * len(pending), per_call * len(pending)
        print(f"estimate: about ${typical:.2f}, at most ${worst:.2f}; {_ledger_line()}")
        if not args.yes:
            print("Re-run with --yes to start.", file=sys.stderr)
            return 2
    try:
        rerun(paths, args.mode, client_factory=lambda model: make_client(model, env_file=args.env_file))
    except (RerunError, BudgetExceeded) as exc:
        print(f"realset rerun: stopped, {exc}", file=sys.stderr)
        return 1
    from printready.realset import last_by, read_jsonl

    rows = last_by(read_jsonl(rerun_runs(paths, args.mode)), "image").values()
    if args.mode == "rules":
        same = sum(1 for r in rows if r.get("fixed_matches_original") is True)
        differs = sum(1 for r in rows if r.get("fixed_matches_original") is False)
        print(f"fixed.png identical to the original run: {same}; different: {differs}")
    print(f"{args.mode}: {len(status(paths, args.mode)['pending'])} still unsettled; {_ledger_line()}")
    return 0
