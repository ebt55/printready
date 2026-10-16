"""`printready bench report`: score predictions.jsonl against the manifest's labels.

Writes to results/bench/<split>/:
- report.md     headline table, confusion matrices, fixer agreement, fix success, outcomes, and every
                disagreement with the ground-truth value, its threshold and what the detector measured
- metrics.json  the same numbers for the UI's Results screen (its documented schema, plus a flat
                `heat` list: check x expected x predicted counts)
- confusion.png one confusion matrix per deterministic check plus the outcome matrix

Vision (text_garbled, text_small) is scored when `bench run --vision` has written vision.jsonl
(a live run on the text family). Agent mode is not run on the benchmark.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from printready.bench.generate import read_manifest
from printready.bench.labels import Thresholds
from printready.bench.run import default_manifest, limit_rows, results_dir
from printready.profile import load_profile
from printready.types import (
    DETERMINISTIC_CHECK_IDS,
    OUTCOMES,
    PRODUCT_CHECK_IDS,
    Artwork,
    Finding,
    Report,
    Step,
    outcome,
)

STATUSES = ("pass", "warn", "fail", "skip")
FLAGGED = ("warn", "fail")
ERROR = "error"  # no prediction (the detector or pipeline raised)
FIX_IOU_MIN = 0.98


# --- reading ----------------------------------------------------------------------------------------


def load_predictions(path: Path) -> dict[str, dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as fh:
        return {p["id"]: p for p in (json.loads(line) for line in fh if line.strip())}


def _status(pred: dict | None, stage: str, check: str) -> str:
    entry = ((pred or {}).get(stage) or {}).get(check)
    return entry["status"] if entry else ERROR


def _fixer(pred: dict | None, stage: str, check: str) -> str:
    entry = ((pred or {}).get(stage) or {}).get(check)
    return entry["fixer"] if entry else ERROR


def _label(status: str, fixer: str) -> str:
    return f"{status}/{fixer}" if status in FLAGGED else status


# --- describing a row ----------------------------------------------------------------------------


def describe_param(row: dict[str, Any]) -> str:
    p, gt = row["param"], row["gt"]
    return {
        "clean": lambda: row["kind"],
        "resolution": lambda: f"ppi {p['ppi']}",
        "background": lambda: p["background"],
        "islands": lambda: f"gap {p['gap_in']} in",
        "soft_alpha": lambda: f"ramp {p['ramp_in']} in ({p['ramp_px']} px, {p['style']})",
        "edge_crop": lambda: f"case {p['case']}, run {gt['edge_run_in']:.3f} in",
        "text": lambda: f"{p['variant']} {p['word']}",
    }[row["family"]]()


def describe_gt(row: dict[str, Any], check: str, th: Thresholds) -> str:
    """The ground-truth quantity that decides `check`, against its threshold(s)."""
    gt = row["gt"]
    if check == "file":
        return (f"{gt['file_bytes'] / 1e6:.2f} MB, short side {gt['min_side_px']} px "
                f"(limits {th.max_upload_bytes / 1e6:g} MB, 64 px)")
    if check == "resolution":
        basis = "canvas" if gt["opaque"] else "subject bbox"
        return f"PPI {gt['ppi']:.1f} from the {basis} (floor {th.ppi_floor:g}, target {th.ppi_target:g})"
    if check == "background":
        if not gt["opaque"]:
            return "real alpha"
        return (f"ring uniformity {gt['ring_uniformity']:.3f} (auto at >= {th.bg_ring_uniform_frac:g}), "
                f"ring max dE {gt['ring_de_max']:.2f} from its mean (tolerance {th.bg_delta_e:g})")
    if gt["opaque"] and check in ("soft_alpha", "edge_crop", "islands"):
        return "opaque image: no subject until the background is removed"
    if check == "soft_alpha":
        return (f"ramp {gt['ramp_in']:.4f} in ({gt['ramp_px']} px) "
                f"(warn above {th.soft_alpha_max_in:g} in)")
    if check == "edge_crop":
        return (f"longest edge run {gt['edge_run_in']:.3f} in ({gt['edge_run_px']} px) "
                f"(fail above {th.edge_cut_min_run_in:g} in)")
    if check == "islands":
        if gt["parts"] == 1:
            return "one part"
        return (f"gap {gt['gap_in']:.3f} in (merges below {th.merge_gap_in:g}, "
                f"bridgeable to {th.bridge_gap_in:g})")
    return ""


def describe_measured(pred: dict | None, check: str, limit: int = 160) -> str:
    entry = ((pred or {}).get("before") or {}).get(check)
    if not entry:
        return "; ".join((pred or {}).get("errors") or ["no prediction"])
    parts = [f"{k}={v}" for k, v in entry.get("measured", {}).items()
             if v is None or isinstance(v, (int, float, str, bool))]
    text = ", ".join(parts)
    return text if len(text) <= limit else text[: limit - 3] + "..."


# --- metrics --------------------------------------------------------------------------------------


def _matrix(counts: dict[str, Counter], rows: list[str], cols: list[str]) -> dict[str, Any]:
    return {"rows": rows, "cols": cols, "counts": [[counts[r][c] for c in cols] for r in rows]}


def _rate(k: int, n: int) -> float | None:
    return round(k / n, 4) if n else None


def check_metrics(rows, preds, check: str) -> dict[str, Any]:
    counts: dict[str, Counter] = defaultdict(Counter)
    flagged_n = exact = detected = 0
    by_status: dict[str, list[int]] = {s: [0, 0] for s in FLAGGED}
    clean_n = clean_flag = 0
    fix_n = fix_agree = 0
    for row in rows:
        pred = preds.get(row["id"])
        exp = row["expected"][check]
        got_s, got_f = _status(pred, "before", check), _fixer(pred, "before", check)
        counts[exp["status"]][got_s] += 1
        if exp["status"] in FLAGGED:
            flagged_n += 1
            exact += got_s == exp["status"]
            detected += got_s in FLAGGED
            by_status[exp["status"]][0] += 1
            by_status[exp["status"]][1] += got_s == exp["status"]
            if got_s in FLAGGED:
                fix_n += 1
                fix_agree += got_f == exp["fixer"]
        if row["family"] == "clean":
            clean_n += 1
            clean_flag += got_s != "pass"
    expected_rows = [s for s in STATUSES if counts.get(s)]
    cols = list(STATUSES) + ([ERROR] if any(c[ERROR] for c in counts.values()) else [])
    return {
        "n": len(rows),
        "matrix": _matrix(counts, expected_rows, cols),
        "recall": _rate(exact, flagged_n),
        "detected": _rate(detected, flagged_n),
        "recall_by_status": {s: {"n": n, "hit": k, "rate": _rate(k, n)} for s, (n, k) in by_status.items() if n},
        "n_expected_flagged": flagged_n,
        "clean_false_flag": _rate(clean_flag, clean_n),
        "clean_false_flags": {"n": clean_n, "flagged": clean_flag},
        "fixer_agreement": _rate(fix_agree, fix_n),
        "fixer_pairs": {"n": fix_n, "agree": fix_agree},
    }


def disagreements(rows, preds, th: Thresholds) -> list[dict[str, Any]]:
    """Every (sample, check) whose BEFORE status, or fixer on a warn/fail, differs from the label."""
    out = []
    for row in rows:
        pred = preds.get(row["id"])
        for check in DETERMINISTIC_CHECK_IDS:
            exp = row["expected"][check]
            got_s, got_f = _status(pred, "before", check), _fixer(pred, "before", check)
            same = got_s == exp["status"] and (got_s not in FLAGGED or got_f == exp["fixer"])
            if not same:
                out.append({
                    "id": row["id"], "family": row["family"], "param": describe_param(row), "check": check,
                    "expected": _label(exp["status"], exp["fixer"]), "predicted": _label(got_s, got_f),
                    "ground_truth": describe_gt(row, check, th), "measured": describe_measured(pred, check),
                })
    return out


def expected_auto(row: dict[str, Any]) -> bool:
    return any(v["status"] in FLAGGED and v["fixer"] == "auto" for c, v in row["expected"].items()
               if c in DETERMINISTIC_CHECK_IDS)


def fix_success(rows, preds) -> dict[str, Any]:
    """Whole rules pipeline on expected-auto samples: final deterministic checks all pass, no step
    damaged, and the final subject matches the ground truth (IoU >= 0.98 outside a 2 px edge band)."""
    results = []
    for row in rows:
        if not expected_auto(row):
            continue
        pred = preds.get(row["id"]) or {}
        reasons = list(pred.get("errors") or [])
        for check in DETERMINISTIC_CHECK_IDS:
            status = _status(pred, "after", check)
            if status != "pass":
                reasons.append(f"final {check} {status}")
        reasons += [f"{s['fix']} damaged" for s in pred.get("steps", []) if s.get("damaged")]
        iou = pred.get("iou")
        if iou is None:
            reasons.append("no final subject to compare")
        elif iou < FIX_IOU_MIN:
            reasons.append(f"subject IoU {iou:.4f} < {FIX_IOU_MIN}")
        results.append({"id": row["id"], "family": row["family"], "param": describe_param(row),
                        "ok": not reasons, "iou": iou, "reasons": reasons,
                        "steps": [s["fix"] + ("" if s["ok"] else " (refused)") for s in pred.get("steps", [])]})
    by_family: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in results:
        by_family[r["family"]][0] += 1
        by_family[r["family"]][1] += r["ok"]
    ok = sum(r["ok"] for r in results)
    return {"n": len(results), "ok": ok, "rate": _rate(ok, len(results)),
            "by_family": {f: {"n": n, "ok": k} for f, (n, k) in by_family.items()},
            "rows": results}


def outcome_metrics(rows, preds) -> dict[str, Any]:
    counts: dict[str, Counter] = defaultdict(Counter)
    misses = []
    for row in rows:
        pred = preds.get(row["id"]) or {}
        got = pred.get("outcome") or ERROR
        counts[row["outcome"]][got] += 1
        if got != row["outcome"]:
            misses.append({"id": row["id"], "family": row["family"], "param": describe_param(row),
                           "expected": row["outcome"], "predicted": got,
                           "final": ", ".join(f"{c} {v['status']}/{v['fixer']}"
                                              for c, v in (pred.get("after") or {}).items()
                                              if v["status"] != "pass") or "all pass",
                           "steps": ", ".join(s["fix"] + ("" if s["ok"] else " (refused)")
                                              for s in pred.get("steps", [])) or "none",
                           "handoff": pred.get("handoff_reason")})
    cols = list(OUTCOMES) + ([ERROR] if any(c[ERROR] for c in counts.values()) else [])
    agree = sum(counts[o][o] for o in OUTCOMES)
    return {"n": len(rows), "agree": agree, "accuracy": _rate(agree, len(rows)),
            "matrix": _matrix(counts, list(OUTCOMES), cols), "misses": misses}


ABSENT = "absent"  # product_fit is reported only when fit_shape changed the product


def final_agreement(rows, preds) -> dict[str, dict[str, Any]]:
    """Final (after the pipeline) status per check vs the manifest's expected_final, including
    product_fit (expected and predicted either present with a status, or absent)."""
    out = {}
    for check in (*DETERMINISTIC_CHECK_IDS, *PRODUCT_CHECK_IDS):
        n = agree = 0
        for row in rows:
            n += 1
            want = row["expected_final"].get(check, ABSENT)
            entry = ((preds.get(row["id"]) or {}).get("after") or {}).get(check)
            got = entry["status"] if entry else (ABSENT if check in PRODUCT_CHECK_IDS else ERROR)
            agree += got == want
        out[check] = {"n": n, "agree": agree, "rate": _rate(agree, n)}
    return out


VISION_POSITIVE = {"text_garbled": "fail", "text_small": "warn"}
DISABLED_NOTE = "disabled by default (see docs/vision-notes.md)"


def _vision_items(entry: dict | None) -> list[dict[str, Any]]:
    return ((entry or {}).get("measured") or {}).get("items") or []


def _cap_text(item: dict[str, Any]) -> str:
    """Cap height as reported: from the model's cap_height_frac (first vision version) or measured
    by code inside the model's text box (later versions)."""
    pt = item.get("cap_height_pt")
    pt_text = "n/a" if pt is None else f"{pt} pt"
    if item.get("cap_height_frac") is not None:
        return f"{item['cap_height_frac']} -> {pt_text}"
    return f"{pt_text} (measured in box)"


def vision_metrics(rows, preds, vision: dict[str, dict], run_info: dict | None) -> dict[str, Any]:
    """Precision and recall of the live vision checks on the text family. A `skip` (unreadable
    answer, API error) counts as not flagged; a sample that was not run is left out and counted."""
    text_rows = [r for r in rows if r["family"] == "text"]
    out: dict[str, Any] = {"model": (run_info or {}).get("model"), "cost_usd": (run_info or {}).get("cost_usd"),
                           "n": len(text_rows)}
    answered = [v["findings"] for v in vision.values() if v.get("findings")]
    disabled = {check for check in VISION_POSITIVE
                if (check == "text_small" and (run_info or {}).get("text_small_enabled") is False)
                or (answered and not any(check in f for f in answered))}
    for check, positive in VISION_POSITIVE.items():
        if check in disabled:
            out[check] = {"disabled": True, "note": DISABLED_NOTE, "precision": None, "recall": None, "n": 0}
            continue
        c: Counter = Counter()
        for row in text_rows:
            findings = (vision.get(row["id"]) or {}).get("findings")
            if not findings or check not in findings:
                c["not_run"] += 1
                continue
            got = findings[check]["status"]
            c["skip"] += got == "skip"
            exp_pos, got_pos = row["expected"][check]["status"] == positive, got in FLAGGED
            c[("tp" if got_pos else "fn") if exp_pos else ("fp" if got_pos else "tn")] += 1
        out[check] = {"precision": _rate(c["tp"], c["tp"] + c["fp"]), "recall": _rate(c["tp"], c["tp"] + c["fn"]),
                      "n": c["tp"] + c["fp"] + c["fn"] + c["tn"],
                      **{k: c[k] for k in ("tp", "fp", "fn", "tn", "skip", "not_run")}}
    misses = []
    threshold_pt = None
    for row in text_rows:
        findings = (vision.get(row["id"]) or {}).get("findings")
        if not findings:
            continue
        items = _vision_items(findings.get("text_small")) or _vision_items(findings.get("text_garbled"))
        threshold_pt = threshold_pt or ((findings.get("text_small") or {}).get("measured") or {}).get(
            "threshold_cap_pt")
        for check in VISION_POSITIVE:
            if check in disabled or check not in findings:
                continue
            exp, got = row["expected"][check], findings[check]
            if got["status"] == exp["status"]:
                continue
            measured = got.get("measured") or {}
            misses.append({
                "id": row["id"], "variant": row["param"]["variant"], "check": check,
                "planted": row["param"]["word"], "intended": row["param"]["intended"],
                "expected": _label(exp["status"], exp["fixer"]), "predicted": _label(got["status"], got["fixer"]),
                "gt_cap_pt": row["gt"].get("cap_height_pt"),
                "seen": "; ".join(f"{i.get('seen')} -> {i.get('intended')}" + (" (garbled)" if i.get("garbled") else "")
                                  for i in items) or "no text",
                "model_cap": "; ".join(_cap_text(i) for i in items) or "n/a",
                "reason": measured.get("error") or measured.get("reason"),
            })
    out["threshold_cap_pt"] = threshold_pt
    out["disagreements"] = misses
    out["outcome_vision"] = _outcome_with_vision(text_rows, preds, vision)
    return out


def _outcome_with_vision(text_rows, preds, vision) -> dict[str, Any]:
    """outcome() on the pipeline's final report plus the live vision findings, vs outcome_vision."""
    n = agree = 0
    misses = []
    for row in text_rows:
        pred, findings = preds.get(row["id"]), (vision.get(row["id"]) or {}).get("findings")
        if not pred or not pred.get("after") or not findings:
            continue
        final = [Finding(check=c, status=v["status"], message="", measured={}, fixer=v["fixer"])
                 for c, v in {**pred["after"], **findings}.items()]
        history = [Step(fix=st["fix"], ok=st["ok"], damaged=st["damaged"], note="") for st in pred.get("steps", [])]
        art = Artwork(rgba=np.zeros((1, 1, 4), dtype=np.uint8), subject=None, ppi=1.0, history=history)
        got = outcome(art, Report(final), handoff=bool(pred.get("handoff_reason")))
        n += 1
        agree += got == row["outcome_vision"]
        if got != row["outcome_vision"]:
            misses.append({"id": row["id"], "expected": row["outcome_vision"], "predicted": got})
    return {"n": n, "agree": agree, "accuracy": _rate(agree, n), "misses": misses}


def summarize(rows, preds, th: Thresholds, run_info: dict[str, Any] | None, split: str,
              vision: dict[str, dict] | None = None, vision_info: dict | None = None) -> dict[str, Any]:
    checks = {c: check_metrics(rows, preds, c) for c in DETERMINISTIC_CHECK_IDS}
    heat = [{"check": c, "expected": r, "predicted": col, "count": m["matrix"]["counts"][i][j]}
            for c, m in checks.items()
            for i, r in enumerate(m["matrix"]["rows"]) for j, col in enumerate(m["matrix"]["cols"])]
    clean = [r for r in rows if r["family"] == "clean"]
    clean_flagged = [r["id"] for r in clean
                     if any(_status(preds.get(r["id"]), "before", c) != "pass" for c in DETERMINISTIC_CHECK_IDS)]
    dis = disagreements(rows, preds, th)
    for c in checks:
        checks[c]["disagreements"] = sum(d["check"] == c for d in dis)
    summary = {
        "split": split,
        "n": len(rows),
        "predicted": sum(1 for r in rows if r["id"] in preds),
        "errors": sum(1 for r in rows if (preds.get(r["id"]) or {}).get("errors")),
        "statuses": list(STATUSES),
        "checks": checks,
        "heat": heat,
        "clean_images": {"n": len(clean), "any_flag": len(clean_flagged),
                         "rate": _rate(len(clean_flagged), len(clean)), "ids": clean_flagged},
        "fix_success": fix_success(rows, preds),
        "outcome": outcome_metrics(rows, preds),
        "final_agreement": final_agreement(rows, preds),
        "pipeline_before_disagrees": [r["id"] for r in rows
                                      if (preds.get(r["id"]) or {}).get("pipeline_before_agrees") is False],
        "disagreements": dis,
        "run": run_info,
        "note": "Deterministic checks from `bench run`; vision only when `bench run --vision` was run live "
                "(text family). Agent mode is not run on the benchmark.",
    }
    if vision:
        summary["vision"] = vision_metrics(rows, preds, vision, vision_info)
    return summary


# --- writing --------------------------------------------------------------------------------------


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def _md_matrix(m: dict[str, Any]) -> list[str]:
    lines = ["| expected \\ predicted | " + " | ".join(m["cols"]) + " |",
             "|---|" + "---|" * len(m["cols"])]
    for r, counts in zip(m["rows"], m["counts"]):
        cells = [f"**{v}**" if c == r and v else str(v) for c, v in zip(m["cols"], counts)]
        lines.append(f"| {r} | " + " | ".join(cells) + " |")
    return lines


def markdown(s: dict[str, Any]) -> str:
    out = [f"# Planted-defect benchmark: `{s['split']}` split", ""]
    run = s.get("run") or {}
    out.append(f"{s['n']} samples, {s['predicted']} predicted, {s['errors']} with errors"
               + (f"; run took {run['seconds']} s with {run['jobs']} workers" if run else "") + ".")
    out += ["Deterministic checks on the image as given (BEFORE); fix success and outcomes from the whole "
            "rules pipeline (AFTER). Vision checks are scored live and are not in this report; agent mode is "
            "not run on the benchmark.", ""]

    out += ["## Headline", "",
            "| check | expected warn/fail | recall (exact status) | detected (any warn/fail) "
            "| clean false flags | fixer agreement | disagreements |",
            "|---|---|---|---|---|---|---|"]
    for c, m in s["checks"].items():
        cf = m["clean_false_flags"]
        fp = m["fixer_pairs"]
        out.append(f"| {c} | {m['n_expected_flagged']} | {_pct(m['recall'])} | {_pct(m['detected'])} "
                   f"| {cf['flagged']}/{cf['n']} | "
                   + (f"{fp['agree']}/{fp['n']}" if fp["n"] else "n/a") + f" | {m['disagreements']} |")
    fx, oc, cl = s["fix_success"], s["outcome"], s["clean_images"]
    out += ["",
            f"- Clean images with any non-pass check: {cl['any_flag']}/{cl['n']} ({_pct(cl['rate'])}).",
            f"- Fix success on expected-auto samples: {fx['ok']}/{fx['n']} ({_pct(fx['rate'])}).",
            f"- Outcome agreement: {oc['agree']}/{oc['n']} ({_pct(oc['accuracy'])}).", ""]

    out += ["## Confusion matrices (BEFORE)", ""]
    for c, m in s["checks"].items():
        out += [f"### {c}", ""] + _md_matrix(m["matrix"]) + [""]
        rs = m["recall_by_status"]
        if rs:
            out += ["Recall by status: " + ", ".join(f"{k} {v['hit']}/{v['n']}" for k, v in rs.items()), ""]

    out += ["## Fix success (whole rules pipeline, expected-auto samples)", "",
            f"Success = final deterministic checks all pass, no damaged step, subject IoU >= {FIX_IOU_MIN} "
            "against ground truth outside a 2 px edge band.", "",
            "| family | ok / n |", "|---|---|"]
    for f, v in fx["by_family"].items():
        out.append(f"| {f} | {v['ok']}/{v['n']} |")
    failed = [r for r in fx["rows"] if not r["ok"]]
    if failed:
        out += ["", "| sample | parameter | steps | why it failed |", "|---|---|---|---|"]
        out += [f"| {r['id']} | {r['param']} | {', '.join(r['steps']) or 'none'} | {'; '.join(r['reasons'])} |"
                for r in failed]
    out.append("")

    out += ["## Outcome (expected from labels vs `outcome()` after the rules pipeline)", ""]
    out += _md_matrix(oc["matrix"]) + [""]
    if oc["misses"]:
        out += ["| sample | parameter | expected | predicted | final non-pass | steps | handoff |",
                "|---|---|---|---|---|---|---|"]
        out += [f"| {m['id']} | {m['param']} | {m['expected']} | {m['predicted']} | {m['final']} "
                f"| {m['steps']} | {m['handoff'] or ''} |" for m in oc["misses"]]
        out.append("")

    out += ["## Final statuses vs `expected_final`", "", "| check | agree |", "|---|---|"]
    out += [f"| {c} | {v['agree']}/{v['n']} |" for c, v in s["final_agreement"].items()]
    out.append("")

    v = s.get("vision")
    if v:
        cost = f", cost ${v['cost_usd']:.4f}" if v.get("cost_usd") is not None else ""
        out += [f"## Vision (live, text family, {v['model']}{cost})", "",
                "| check | precision | recall | tp | fp | fn | tn | skip | not run |",
                "|---|---|---|---|---|---|---|---|---|"]
        for check in VISION_POSITIVE:
            m = v[check]
            if m.get("disabled"):
                out.append(f"| {check} | {m['note']} | | | | | | | |")
                continue
            out.append(f"| {check} | {_pct(m['precision'])} | {_pct(m['recall'])} | {m['tp']} | {m['fp']} "
                       f"| {m['fn']} | {m['tn']} | {m['skip']} | {m['not_run']} |")
        ov = v["outcome_vision"]
        out += ["", f"Outcome with the vision findings: {ov['agree']}/{ov['n']} agree with `outcome_vision`.", ""]
        if v["disagreements"]:
            if v.get("threshold_cap_pt"):
                out += [f"Text is small below a cap height of {v['threshold_cap_pt']} pt.", ""]
            out += [
                    "| sample | variant | check | planted (intended) | expected | predicted | model read "
                    "| cap height (model frac -> pt, or measured) | true cap pt |",
                    "|---|---|---|---|---|---|---|---|---|"]
            for d in v["disagreements"]:
                reason = f" [{d['reason']}]" if d["reason"] else ""
                out.append(f"| {d['id']} | {d['variant']} | {d['check']} | {d['planted']} ({d['intended']}) "
                           f"| {d['expected']} | {d['predicted']} | {d['seen']}{reason} | {d['model_cap']} "
                           f"| {d['gt_cap_pt']:.2f} |")
            out.append("")

    out += ["## Disagreements (BEFORE), by check", ""]
    if not s["disagreements"]:
        out += ["None.", ""]
    by_check: dict[str, list[dict]] = defaultdict(list)
    for d in s["disagreements"]:
        by_check[d["check"]].append(d)
    for c, items in by_check.items():
        out += [f"### {c} ({len(items)})", "",
                "| sample | parameter | expected | predicted | ground truth vs threshold | detector measured |",
                "|---|---|---|---|---|---|"]
        out += [f"| {d['id']} | {d['param']} | {d['expected']} | {d['predicted']} | {d['ground_truth']} "
                f"| {d['measured']} |" for d in items]
        out.append("")
    if s["pipeline_before_disagrees"]:
        out += ["Samples where the pipeline's own BEFORE report differed from `run_checks`: "
                + ", ".join(s["pipeline_before_disagrees"]), ""]
    return "\n".join(out)


# Colours from the dataviz reference palette: one blue ramp (light -> dark) for row share,
# text in ink tokens, the chart surface for empty cells and the gaps between cells.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_ON_DARK = "#f0efec"
MUTED = "#52514e"
BLUE_RAMP = ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5",
             "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]


def figure(s: dict[str, Any], path: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    cmap = LinearSegmentedColormap.from_list("blue", BLUE_RAMP)
    panels = [(c, m["matrix"]) for c, m in s["checks"].items()] + [("outcome", s["outcome"]["matrix"])]
    cols = 4
    nrows = (len(panels) + cols - 1) // cols
    fig, axes = plt.subplots(nrows, cols, figsize=(cols * 3.3, nrows * 3.1), facecolor=SURFACE)
    for ax in axes.flat:
        ax.set_facecolor(SURFACE)
        ax.axis("off")
    for ax, (title, m) in zip(axes.flat, panels):
        rows, cs, counts = m["rows"], m["cols"], m["counts"]
        for i, row_counts in enumerate(counts):
            total = sum(row_counts) or 1
            for j, v in enumerate(row_counts):
                share = v / total
                colour = SURFACE if v == 0 else cmap(0.15 + 0.85 * share)
                ax.add_patch(plt.Rectangle((j, i), 1, 1, facecolor=colour, edgecolor=SURFACE, linewidth=2))
                if v:
                    ax.text(j + 0.5, i + 0.5, str(v), ha="center", va="center", fontsize=10,
                            color=INK_ON_DARK if share > 0.55 else INK)
                elif v == 0:
                    ax.text(j + 0.5, i + 0.5, "0", ha="center", va="center", fontsize=8, color="#c3c2b7")
        ax.set_xlim(0, len(cs))
        ax.set_ylim(len(rows), 0)
        ax.axis("on")
        ax.set_xticks([j + 0.5 for j in range(len(cs))], cs, fontsize=8, color=MUTED)
        ax.set_yticks([i + 0.5 for i in range(len(rows))], rows, fontsize=8, color=MUTED)
        ax.tick_params(length=0)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_title(title, fontsize=11, color=INK, loc="left")
        ax.set_xlabel("predicted", fontsize=8, color=MUTED)
        ax.set_ylabel("expected", fontsize=8, color=MUTED)
        ax.set_aspect("equal")
        ax.set_anchor("NW")  # panels with fewer rows stay top-aligned under their titles
    fig.suptitle(f"Planted-defect benchmark, {s['split']} split: expected vs predicted (colour = share of row)",
                 fontsize=12, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    fig.savefig(path, dpi=110, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)
    return path


def report_split(
    split: str,
    root: Path | str = ".",
    *,
    limit: int | None = None,
    manifest: Path | None = None,
    profile_path: Path | None = None,
    log=print,
) -> dict[str, Any]:
    root = Path(root)
    out = results_dir(root, split, limit)
    pred_path = out / "predictions.jsonl"
    if not pred_path.exists():
        raise FileNotFoundError(f"{pred_path} not found; run `printready bench run --split {split}` first")
    manifest = Path(manifest) if manifest else default_manifest(root, split)
    rows = limit_rows(read_manifest(manifest), limit)
    preds = load_predictions(pred_path)
    run_path = out / "run.json"
    run_info = json.loads(run_path.read_text(encoding="utf-8")) if run_path.exists() else None
    if run_info and run_info.get("manifest_sha256") != hashlib.sha256(manifest.read_bytes()).hexdigest():
        log("warning: predictions were made against a different manifest")
    th = Thresholds.from_profile(load_profile(profile_path))
    vision = load_predictions(out / "vision.jsonl") if (out / "vision.jsonl").exists() else None
    vision_path = out / "vision-run.json"
    vision_info = json.loads(vision_path.read_text(encoding="utf-8")) if vision_path.exists() else None
    s = summarize(rows, preds, th, run_info, split, vision, vision_info)
    (out / "metrics.json").write_text(json.dumps(s, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    (out / "report.md").write_text(markdown(s), encoding="utf-8")
    figure(s, out / "confusion.png")
    log(f"bench report --split {split}: {out / 'report.md'}")
    return s
