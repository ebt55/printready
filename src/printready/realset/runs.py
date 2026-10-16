"""`realset run`: one mode over a split at a 3 in die-cut order, one summary line per image.

Blinding (03-EVAL.md): on the test split no tool output may exist before Ebin's pass-1 labels
are complete, so `run` refuses until all sampled images have a pass-1 label.
The spend cap stops a batch cleanly: an image whose run would pass the cap is not recorded, so it
can run later (a "budget" handoff is our limit, not the model's outcome).
PREREG 5: one agent run per image, no reruns, so on the test split agent mode never repeats a
finished image. On dev (tuning only) and in rules mode `force` re-runs; the last runs.jsonl line wins.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

from printready.agent import MAX_TURNS, run_agent
from printready.llm import MAX_TOKENS, ChatClient
from printready.pipeline import run_rules
from printready.profile import Profile, load_profile
from printready.realset import Paths, append_jsonl, last_by, read_jsonl, sample_shas, spec_for
from printready.spend import BudgetExceeded, check_cap, estimate, price_for
from printready.types import RunResult

AGENT_TYPICAL_USD = 0.01  # observed on grok-4.3: 4-5 turns, about $0.008-0.012 per image
AGENT_TURN_TOKENS_IN = 8000  # generous prompt size per turn for the worst case
PRECHECK_USD = {"rules": 0.015, "agent": 0.05}  # room needed before an image starts (one vision call / a typical run)


def pass1_missing(paths: Paths) -> list[str]:
    """Sampled images that do not have a pass-1 label yet."""
    labelled = {r["image"] for r in read_jsonl(paths.labels) if r.get("pass") == 1}
    return [s for s in sample_shas(read_jsonl(paths.manifest)) if s not in labelled]


def select(paths: Paths, sample: bool, only: list[str] | None = None) -> list[dict[str, Any]]:
    """Manifest entries to run: all, the seeded sample, and/or those whose prompt id or sha256
    prefix is in `only` (e.g. ["d07", "16de6b"])."""
    manifest = list(last_by(read_jsonl(paths.manifest), "sha256").values())
    if sample:
        chosen = set(sample_shas(manifest))
        manifest = [e for e in manifest if e["sha256"] in chosen]
    if only:
        manifest = [e for e in manifest if any(e["prompt_id"] == o or e["sha256"].startswith(o) for o in only)]
    return manifest


def may_rerun(split: str, mode: str) -> bool:
    """PREREG 5 binds the test split: one agent run per image there, ever."""
    return not (split == "test" and mode == "agent")


def agent_estimate(model: str, n_images: int) -> tuple[float, float]:
    """(typical, worst case) USD for agent mode on n images; worst = every turn at the limit."""
    per_turn = estimate(price_for(model), tokens_in=AGENT_TURN_TOKENS_IN, tokens_out=MAX_TOKENS)
    worst = (MAX_TURNS + 1) * per_turn  # + one read_text call
    return AGENT_TYPICAL_USD * n_images, worst * n_images


def run_split(
    paths: Paths,
    mode: str,
    items: list[dict[str, Any]],
    client_factory: Callable[[], ChatClient] | None = None,
    force: bool = False,
    profile: Profile | None = None,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Run `mode` on `items` (manifest entries). Agent mode needs `client_factory` (one fresh
    client per image); rules mode runs the vision check only if one is given."""
    if mode == "agent" and client_factory is None:
        raise ValueError("agent mode needs a model client")
    profile = profile or load_profile()
    done = set(last_by(read_jsonl(paths.runs(mode)), "image"))
    rows = []
    for e in items:
        sha = e["sha256"]
        if sha in done and not (force and may_rerun(paths.split, mode)):
            continue
        out_dir = paths.results / mode / sha
        if client_factory is not None:
            check_cap(PRECHECK_USD[mode])  # raises BudgetExceeded: the batch stops before this image
        client = client_factory() if client_factory else None
        image, spec = paths.data / e["file"], spec_for(e["prompt"])
        try:
            if mode == "agent":
                run = run_agent(image, spec, profile, out_dir, client)
            else:
                run = run_rules(image, spec, profile, out_dir, client=client)
        finally:
            if client is not None:
                client.close()
        if run.handoff_reason == "budget":
            raise BudgetExceeded(f"spend cap reached during {e['prompt_id']} {sha[:12]}; it was not recorded")
        row = summarize(run, e, out_dir, paths.root, getattr(client, "model", None))
        append_jsonl(paths.runs(mode), [row])
        rows.append(row)
        log(f"  {e['prompt_id']} {sha[:12]} {mode}: {row['outcome']}"
            + (f" ({row['handoff_reason']})" if row["handoff_reason"] else "")
            + (f" ${row['cost_usd']:.4f}" if row["cost_usd"] else ""))
    return rows


def summarize(run: RunResult, entry: dict[str, Any], out_dir: Path, root: Path, model: str | None) -> dict[str, Any]:
    fixed = out_dir / "fixed.png"
    history = run.art.history if run.art is not None else []

    def statuses(report):
        return {f.check: {"status": f.status, "fixer": f.fixer} for f in report.findings}

    return {
        "image": entry["sha256"],
        "prompt_id": entry["prompt_id"],
        "image_model": entry["model"],
        "mode": run.mode,
        "model": model,
        "outcome": run.outcome,
        "shape": run.art.shape if run.art is not None else None,
        "handoff_reason": run.handoff_reason,
        "before": statuses(run.before),
        "after": statuses(run.after),
        "steps": [{"fix": s.fix, "ok": s.ok, "damaged": s.damaged} for s in history],
        "damaged": any(s.damaged for s in history),
        "cost_usd": round(run.cost_usd, 6),
        "elapsed_s": round(run.elapsed_s, 3),
        "fixed_sha256": hashlib.sha256(fixed.read_bytes()).hexdigest() if fixed.exists() else None,
        "out_dir": out_dir.relative_to(root).as_posix(),
        "customer_message": run.customer_message,
    }
