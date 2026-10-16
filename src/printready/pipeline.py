"""Rules mode (a fixed sequence of checks and fixes) and the output writer both modes share.

Fixed order: load -> check -> remove_background if background fail/auto -> re-check ->
pad_canvas if edge_crop warn/auto or the margin is under the border it will need -> add_border ->
bridge_islands if islands fail/auto -> re-check -> check_text if a client is given -> outcome().

Progress events for the local web UI, `printready serve` (`on_event(dict)`, payloads JSON-ready):
  {"type": "findings", "stage": "before"|"after", "report": Report.to_dict()}
  {"type": "step", "index": n, "step": Step.to_dict(), "preview": "step-<n>-<fix>.png"}
  {"type": "done", "result": RunResult.to_dict()}
  {"type": "error", "message": "..."}
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

from printready.checks import load_failure_report, run_checks
from printready.cutline import cutline_svg
from printready.guard import apply_fix
from printready.imageio import ImageLoadError, load_artwork, save_png
from printready.profile import Profile, load_profile
from printready.render import render_overlay, render_proof
from printready.reporthtml import report_html
from printready.types import Artwork, Finding, Outcome, Report, RunResult, Spec, Step, outcome

EventFn = Callable[[dict[str, Any]], None]
CHECK_FOR_FIX = {"remove_background": "background", "pad_canvas": "edge_crop", "bridge_islands": "islands"}
MAX_MESSAGE_WORDS = 80


def _has(report: Report, check: str, status: str, fixer: str | None = None) -> bool:
    """Whether `check` reported `status` (and `fixer`, if given)."""
    f = report.by_check(check)
    return f is not None and f.status == status and (fixer is None or f.fixer == fixer)


def _needs_pad(report: Report, profile: Profile, will_bridge: bool) -> bool:
    """Pad when the art touches an edge, or its margin is narrower than the border it will get."""
    edge = report.by_check("edge_crop")
    if edge is None or edge.status in ("skip", "fail"):  # fail = art cut off: padding would hide it
        return False
    if edge.status == "warn" and edge.fixer == "auto":
        return True
    margin = edge.measured.get("min_margin_in")
    need = profile.max_bridge_border_in if will_bridge else profile.border_in
    return margin is not None and margin < need


def _vision(art: Artwork, spec: Spec, profile: Profile, client: Any) -> tuple[list[Finding], float]:
    """Text findings from printready.vision and their cost; if the vision check is unavailable or
    fails, two `skip` findings say so (a failure is an outcome, never a crash)."""
    cost0 = float(getattr(client, "cost_usd", 0.0) or 0.0)
    try:
        from printready.vision import check_text

        found = list(check_text(art, spec, profile, client))
    except Exception as exc:  # noqa: BLE001 - a vision failure is an outcome, not a crash
        reason = f"vision check unavailable ({type(exc).__name__}: {exc})"
        found = [Finding(c, "skip", "The text could not be checked.", {"reason": reason}, "none") for c in ("text_garbled", "text_small")]
    return found, float(getattr(client, "cost_usd", 0.0) or 0.0) - cost0


def _mark_refused(after: Report, history: list[Step]) -> None:
    """A refused or reverted corrective fix leaves its finding to a person, with the reason."""
    last = {s.fix: s for s in history}
    for fix, check in CHECK_FOR_FIX.items():
        step, finding = last.get(fix), after.by_check(check)
        if step is None or step.ok or finding is None or finding.status not in ("warn", "fail"):
            continue
        finding.fixer = "person"
        finding.message = f"{finding.message} Our automatic fix did not apply: {step.note}"


# ---------------------------------------------------------------- messages

def _change_phrase(step: Step) -> str | None:
    """How an applied fix reads in the customer message ("We ...")."""
    border = step.measured.get("border_in", 0.1)
    return {
        "remove_background": "removed the plain background",
        "pad_canvas": "added a little space around the edges",
        "add_border": f"added a {border:g} in white border with a cut line",
        "bridge_islands": f"widened the border to {border:.2f} in so the pieces cut as one sticker",
    }.get(step.fix)


def _join_and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def customer_message(result: Outcome, art: Artwork | None, after: Report, spec: Spec) -> str:
    """Rules-mode template: what changed, what the customer must decide, one approve line (< 80 words)."""
    size = f"{spec.size_in:g} in"
    changes = [c for s in (art.history if art else []) if s.ok and (c := _change_phrase(s))]
    parts = [f"We {_join_and(changes)}."] if changes else []
    res = after.by_check("resolution")
    if res is not None and res.status in ("warn", "fail") and res.fixer == "customer":
        m = res.measured  # ppi and the largest sharp sizes
        if res.status == "warn":
            parts.append(
                f"At {size} it prints at {m['ppi']:.0f} PPI; at {m['max_size_in_at_target']:.1f} in or smaller it is fully sharp. "
                f"Keep {size} or choose a smaller size."
            )
        else:
            parts.append(
                f"At {size} it prints at only {m['ppi']:.0f} PPI and will look soft; it is sharp at "
                f"{m['max_size_in_at_target']:.1f} in and acceptable up to {m['max_size_in_at_floor']:.1f} in. Please choose a smaller size."
            )
    parts += [f.message for f in after.findings if f.check != "resolution" and f.status in ("warn", "fail") and f.fixer == "customer"][:1]
    if result == "needs_person":
        reason = next(
            (f.message for f in after.findings if f.status in ("warn", "fail") and f.fixer in ("person", "none", "auto")),
            "something could not be checked automatically.",
        )
        reason = reason[:1].lower() + reason[1:]
        tail = f"Before printing, a person on our team will check this: {reason} We will send you an updated proof."
    else:
        tail = f"If the proof looks right, approve it to print your {size} die-cut sticker."
    while len(" ".join([*parts, tail]).split()) > MAX_MESSAGE_WORDS and parts:
        parts.pop()
    text = " ".join([*parts, tail])
    words = text.split()
    return text if len(words) <= MAX_MESSAGE_WORDS else " ".join(words[:MAX_MESSAGE_WORDS - 1]) + " ..."


def person_notes(art: Artwork | None, after: Report) -> list[str]:
    """One line per thing a person must look at: refused or reverted fixes, findings left to a
    person, and checks that could not be verified."""
    notes = []
    for s in art.history if art else []:
        if s.damaged:
            notes.append(f"{s.fix} damaged the art and was reverted: {s.note}")
        elif not s.ok:
            notes.append(f"{s.fix} was refused: {s.note}")
    for f in after.findings:
        if f.status in ("warn", "fail") and f.fixer in ("person", "none", "auto"):
            notes.append(f"{f.check} {f.status} ({f.fixer}): {f.message}")
        elif f.status == "skip":
            notes.append(f"{f.check} not verified: {f.measured.get('reason', f.message)}")
    return notes


# ---------------------------------------------------------------- rules mode

def run_rules(
    path: str | Path,
    spec: Spec,
    profile: Profile,
    out_dir: str | Path,
    client: Any = None,
    on_event: EventFn | None = None,
) -> RunResult:
    """Run rules mode on one image, write the outputs to `out_dir`, return the RunResult."""
    t0 = time.perf_counter()
    emit = on_event or (lambda event: None)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        try:
            original = load_artwork(path, spec, profile)
        except ImageLoadError as exc:
            report = load_failure_report(str(exc))
            emit({"type": "findings", "stage": "before", "report": report.to_dict()})
            result = outcome(None, report)
            run = RunResult(
                mode="rules", art=None, before=report, after=report, outcome=result,
                customer_message=customer_message(result, None, report, spec),
                person_notes=person_notes(None, report), spec=spec, profile=profile,
            )
            return _complete(run, out_dir, emit, t0)

        before = run_checks(original, spec, profile)
        emit({"type": "findings", "stage": "before", "report": before.to_dict()})
        art, previews = original, {}

        def run_fix(fix: str) -> None:
            """Apply one fix through the damage guard, save its preview and announce it."""
            nonlocal art
            art = apply_fix(fix, art, spec, profile).art
            n = len(previews) + 1
            previews[f"step-{n}"] = name = f"step-{n}-{fix}.png"
            save_png(art.rgba, out_dir / name)
            emit({"type": "step", "index": n, "step": art.history[-1].to_dict(), "preview": name})

        current = before
        if _has(before, "background", "fail", "auto"):
            run_fix("remove_background")
            current = run_checks(art, spec, profile)
        if art.subject is not None:
            will_bridge = _has(current, "islands", "fail", "auto")
            if _needs_pad(current, profile, will_bridge):
                run_fix("pad_canvas")
            run_fix("add_border")
            if will_bridge:
                run_fix("bridge_islands")

        after = run_checks(art, spec, profile)
        cost = 0.0
        if client is not None:
            text, cost = _vision(art, spec, profile, client)
            after.findings.extend(text)
        _mark_refused(after, art.history)
        emit({"type": "findings", "stage": "after", "report": after.to_dict()})
        result = outcome(art, after)
        run = RunResult(
            mode="rules", art=art, before=before, after=after, outcome=result,
            customer_message=customer_message(result, art, after, spec),
            person_notes=person_notes(art, after), cost_usd=cost, outputs=previews,
            spec=spec, profile=profile, original=original,
        )
        return _complete(run, out_dir, emit, t0)
    except Exception as exc:
        emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        raise


def _complete(run: RunResult, out_dir: Path, emit: EventFn, t0: float) -> RunResult:
    run.elapsed_s = time.perf_counter() - t0
    write_outputs(run, out_dir)
    emit({"type": "done", "result": run.to_dict()})
    return run


# ---------------------------------------------------------------- outputs

def write_outputs(run: RunResult, out_dir: str | Path) -> dict[str, str]:
    """Write the per-image outputs for a rules or agent run and return {name: file name in out_dir}.

    report.json, fixed.png, cutline.svg (only if a cut was built), proof.png, overlay.png,
    customer_message.md, report.html. Entries already in run.outputs (step previews, an agent's
    log.jsonl) are kept. Also sets run.outputs to the returned dict.
    """
    if run.spec is None:
        raise ValueError("RunResult.spec is required to write outputs")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    spec, profile, art = run.spec, run.profile or load_profile(), run.art
    original = run.original
    if original is None and art is not None and art.meta.get("path"):
        try:
            original = load_artwork(art.meta["path"], spec, profile)
        except ImageLoadError:
            original = None

    outputs = dict(run.outputs)
    images = {}
    if art is not None:
        save_png(art.rgba, out_dir / "fixed.png")
        outputs["fixed"] = "fixed.png"
        if art.cut is not None:
            (out_dir / "cutline.svg").write_text(cutline_svg(art, spec, profile), encoding="utf-8")
            outputs["cutline"] = "cutline.svg"
        images["after"] = render_proof(art, spec, profile)
        images["after"].save(out_dir / "proof.png")
        outputs["proof"] = "proof.png"
    if original is not None:
        images["before"] = render_overlay(original, run.before)
        images["before"].save(out_dir / "overlay.png")
        outputs["overlay"] = "overlay.png"
    (out_dir / "customer_message.md").write_text(run.customer_message + "\n", encoding="utf-8")
    outputs.update(customer_message="customer_message.md", report="report.json", html="report.html")
    run.outputs = outputs
    (out_dir / "report.json").write_text(json.dumps(run.to_dict(), indent=2) + "\n", encoding="utf-8")
    (out_dir / "report.html").write_text(report_html(run, images), encoding="utf-8")
    return outputs
