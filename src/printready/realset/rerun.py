"""Declared PREREG deviation (addendum 1): re-attempt runs that never reached a model.

A run qualifies only if EVERY model call it made returned HTTP 403 or 429 and billed zero tokens
(rules: the vision call; agent: every call in log.jsonl). Anything that billed a token is never
listed and never re-run. Re-attempts use the unchanged client, backoff, prompts and models and
write to results/realset/<split>-rerun/; results/realset/<split>/ is never touched.

A listed run is settled by the first attempt that bills at least one token: that attempt is final
whatever it returns, and settled runs are never attempted again. Every attempt is recorded in
attempts.jsonl (number, time, tokens). After the deadline in the list header, the runs still
unsettled are recorded as a final hand-off "error".
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from printready.agent import run_agent
from printready.llm import ChatClient
from printready.pipeline import run_rules
from printready.profile import Profile, load_profile
from printready.realset import MODES, Paths, append_jsonl, last_by, read_jsonl, spec_for
from printready.realset.runs import PRECHECK_USD, hit_cap, summarize
from printready.spend import BudgetExceeded, check_cap
from printready.types import VISION_CHECK_IDS

INFRA_ERRORS = ("HTTP 403", "HTTP 429")  # out of credit / model at capacity: the model never ran
LIST_NAME = "rerun-list.txt"


class RerunError(ValueError):
    """The rerun list is missing, malformed, or lists a run that does not qualify."""


def rerun_root(paths: Paths) -> Path:
    return paths.root / "results" / "realset" / f"{paths.split}-rerun"


def rerun_runs(paths: Paths, mode: str) -> Path:
    return rerun_root(paths) / mode / "runs.jsonl"


# ---------------------------------------------------------------- qualification

def model_calls(paths: Paths, mode: str, row: dict[str, Any]) -> list[dict[str, Any]]:
    """The model calls of an original run as its files record them. Agent: the call records in
    log.jsonl. Rules: the vision check in report.json (an API error is one failed call; anything
    else is treated as a call that answered)."""
    out_dir = paths.root / row["out_dir"]
    if mode == "agent":
        return [c for c in read_jsonl(out_dir / "log.jsonl") if c.get("type") == "call"]
    report = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    vision = [f for f in report["after"]["findings"] if f["check"] in VISION_CHECK_IDS]
    if not vision:
        return []
    m = vision[0]["measured"]
    if vision[0]["status"] == "skip" and m.get("reason") == "api error":
        return [{"status": "error", "error": str(m.get("error", "")), "tokens_in": 0, "tokens_out": 0}]
    return [{"status": "ok", "error": None}]


def qualifies(paths: Paths, mode: str, row: dict[str, Any]) -> bool:
    """Every model call returned HTTP 403/429 and nothing was billed."""
    if float(row.get("cost_usd") or 0) > 0:
        return False
    calls = model_calls(paths, mode, row)
    return bool(calls) and all(
        c.get("status") == "error" and str(c.get("error") or "").startswith(INFRA_ERRORS)
        and not (c.get("tokens_in") or c.get("tokens_out") or c.get("cost_usd"))
        for c in calls
    )


def write_list(paths: Paths, deadline: str) -> dict[str, list[str]]:
    """Write rerun-list.txt (deadline in the header) and return {mode: [sha, ...]}."""
    _parse_deadline(deadline)
    listed = {m: sorted(r["image"] for r in last_by(read_jsonl(paths.runs(m)), "image").values()
                        if qualifies(paths, m, r)) for m in MODES}
    lines = [
        "# printready rerun list (PREREG addendum 1): runs whose every model call returned HTTP 403 or 429",
        "# with zero tokens. Nothing that billed a token is listed.",
        f"# split: {paths.split}",
        f"# deadline: {deadline}",
        f"# created: {_now_iso()}",
    ] + [f"{m} {sha}" for m in MODES for sha in listed[m]]
    path = paths.results / LIST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return listed


def read_list(paths: Paths) -> tuple[datetime, dict[str, list[str]]]:
    path = paths.results / LIST_NAME
    if not path.exists():
        raise RerunError(f"{path} does not exist; run `realset rerun-list` first")
    deadline, listed = None, {m: [] for m in MODES}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# deadline:"):
            deadline = _parse_deadline(line.split(":", 1)[1].strip())
        elif line.strip() and not line.startswith("#"):
            mode, sha = line.split()
            if mode not in MODES:
                raise RerunError(f"bad line in {path.name}: {line!r}")
            listed[mode].append(sha)
    if deadline is None:
        raise RerunError(f"{path.name} has no '# deadline:' header")
    return deadline, listed


# ---------------------------------------------------------------- re-attempts

def status(paths: Paths, mode: str) -> dict[str, list[str]]:
    """Listed runs of `mode` split into settled (an attempt billed a token), final (recorded at
    the deadline) and pending (may be attempted)."""
    _, listed = read_list(paths)
    attempts = [a for a in read_jsonl(rerun_root(paths) / "attempts.jsonl") if a["mode"] == mode]
    settled = {a["image"] for a in attempts if a["billed"]}
    final = set(last_by(read_jsonl(rerun_runs(paths, mode)), "image"))
    return {
        "settled": [s for s in listed[mode] if s in settled],
        "final": [s for s in listed[mode] if s in final and s not in settled],
        "pending": [s for s in listed[mode] if s not in settled and s not in final],
    }


def rerun(
    paths: Paths,
    mode: str,
    client_factory: Callable[[str], ChatClient],
    now: datetime | None = None,
    profile: Profile | None = None,
    log: Callable[[str], None] = print,
) -> list[dict[str, Any]]:
    """Attempt every pending listed run of `mode` once (before the deadline), or record them as
    final hand-off "error" (after it). Returns the attempt records written."""
    deadline, listed = read_list(paths)
    originals = last_by(read_jsonl(paths.runs(mode)), "image")
    bad = [s for s in listed[mode] if s not in originals or not qualifies(paths, mode, originals[s])]
    if bad:
        raise RerunError(f"{len(bad)} listed {mode} runs do not qualify (they billed tokens or are unknown): "
                         + ", ".join(s[:12] for s in bad))
    now = now or datetime.now().astimezone()
    pending = status(paths, mode)["pending"]
    tried = {}
    for a in read_jsonl(rerun_root(paths) / "attempts.jsonl"):
        if a["mode"] == mode:
            tried[a["image"]] = max(tried.get(a["image"], 0), a["attempt"])
    if now >= deadline:
        rows = [_deadline_row(originals[s], tried.get(s, 0)) for s in pending]
        append_jsonl(rerun_runs(paths, mode), rows)
        log(f"  deadline {deadline.isoformat()} passed: {len(rows)} unsettled {mode} runs recorded as hand-off 'error'")
        return []
    manifest = last_by(read_jsonl(paths.manifest), "sha256")
    profile = profile or load_profile()
    records = []
    for sha in pending:
        check_cap(PRECHECK_USD[mode])  # stops the batch before an image that might not fit
        original, entry = originals[sha], manifest[sha]
        attempt = tried.get(sha, 0) + 1
        out_dir = rerun_root(paths) / mode / sha
        client = client_factory(original["model"])
        try:
            image, spec = paths.data / entry["file"], spec_for(entry["prompt"])
            if mode == "agent":
                run = run_agent(image, spec, profile, out_dir, client)
            else:
                run = run_rules(image, spec, profile, out_dir, client=client)
        finally:
            client.close()
        if hit_cap(run):
            raise BudgetExceeded(f"spend cap reached during {sha[:12]}; the attempt was not recorded")
        tokens = sum(int(c.get("tokens_in") or 0) + int(c.get("tokens_out") or 0) for c in client.calls)
        record = {
            "mode": mode, "image": sha, "attempt": attempt, "ts": _now_iso(), "billed": tokens >= 1,
            "tokens": tokens, "cost_usd": round(run.cost_usd, 6), "outcome": run.outcome,
            "errors": [c.get("error") for c in client.calls if c.get("status") == "error"][:3],
        }
        append_jsonl(rerun_root(paths) / "attempts.jsonl", [record])
        records.append(record)
        if record["billed"]:  # settled: this attempt is final whatever it returned
            row = summarize(run, entry, out_dir, paths.root, original["model"])
            row.update(attempt=attempt, rerun_ts=record["ts"],
                       fixed_matches_original=row["fixed_sha256"] == original.get("fixed_sha256"))
            append_jsonl(rerun_runs(paths, mode), [row])
        log(f"  {entry['prompt_id']} {sha[:12]} {mode} attempt {attempt}: "
            + (f"settled, {run.outcome}, {tokens} tokens" if record["billed"] else f"no tokens ({record['errors'][:1]})"))
    return records


def _deadline_row(original: dict[str, Any], attempts: int) -> dict[str, Any]:
    return {**original, "outcome": "needs_person", "handoff_reason": "error", "attempt": attempts,
            "rerun_ts": _now_iso(), "rerun_final": "deadline"}


def _parse_deadline(text: str) -> datetime:
    try:
        deadline = datetime.fromisoformat(text)
    except ValueError:
        raise RerunError(f"deadline must look like 2026-10-19T18:00+05:30, got {text!r}") from None
    if deadline.tzinfo is None:
        raise RerunError(f"deadline needs a UTC offset, e.g. 2026-10-19T18:00+05:30, got {text!r}")
    return deadline


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
