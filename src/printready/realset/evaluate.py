"""`realset eval`: agreement with Ebin's labels, bad fixes, cost and latency, and the PREREG
keep-or-remove verdict. Writes results/realset/<split>/eval.md and summary.json (the UI's
Results screen reads summary.json).

Pass-1 labels record a fact (03-EVAL.md): ready_diecut, fixable_diecut, scene, needs_person.
The PREREG mapping to outcomes is ready_diecut -> ready, fixable_diecut -> fixable,
scene -> fixable (the tool offers a rounded-rectangle sticker), needs_person -> needs_person.
Agreement is also reported with scene -> needs_person, side by side, so a reader sees how much
of the number is that policy. The verdict uses the PREREG mapping.

Keep-or-remove (PREREG 4): agent mode becomes the default only if, on the labelled images, it
agrees with Ebin on at least KEEP_MARGIN more images than rules mode AND it has no more bad fixes
(pass-2 unacceptable, including rounded-rectangle proofs, or damaged) than rules mode. Until
every sampled image has a pass-1 label, both modes have run on all of them, and every pass-2
proof is labelled, the verdict is "pending".
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from typing import Any

from printready.realset import MODES, Paths, last_by, read_jsonl, sample_shas, write_json
from printready.realset.label import PASS1_LABELS, labels_by_pass
from printready.types import OUTCOMES

KEEP_MARGIN = 5
PREREG_MAPPING = {"ready_diecut": "ready", "fixable_diecut": "fixable", "scene": "fixable",
                  "needs_person": "needs_person",
                  "ready": "ready", "fixable": "fixable"}  # the last two: labels from the 3-key page
SCENE_AS_PERSON = {**PREREG_MAPPING, "scene": "needs_person"}


RERUN_LABEL = "rerun (PREREG addendum 1)"


def evaluate(paths: Paths, with_rerun: bool = False) -> dict[str, Any]:
    """The preregistered numbers; with `with_rerun`, also the numbers with the declared reruns
    (PREREG addendum 1) in place of the runs that never reached a model, side by side."""
    manifest = last_by(read_jsonl(paths.manifest), "sha256")
    sample = sample_shas(list(manifest.values()))
    pass1, pass2 = labels_by_pass(paths.labels)
    runs = {m: last_by(read_jsonl(paths.runs(m)), "image") for m in MODES}
    labelled = [s for s in sample if s in pass1]
    scenes = [s for s in labelled if pass1[s] == "scene"]
    modes, paired = _score(runs, sample, labelled, scenes, pass1, pass2)
    by_model: dict[str, dict[str, int]] = {}
    for row in runs["rules"].values():
        counts = by_model.setdefault(row["image_model"], {o: 0 for o in OUTCOMES})
        counts[row["outcome"]] += 1

    summary = {
        "split": paths.split,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_images": len(manifest),
        "sample": {"n": len(sample), "labelled_pass1": len(labelled), "scenes": len(scenes)},
        "labels": {
            "pass1": dict(Counter(pass1[s] for s in labelled)),
            "pass2": dict(Counter(pass2.values())),
        },
        "mapping": {"prereg": PREREG_MAPPING, "scene_as_person": SCENE_AS_PERSON},
        "modes": modes,
        "paired": paired,
        "verdict": _verdict(sample, labelled, modes, paired),
        "rules_by_image_model": by_model,
        "images": [_card(e, pass1, pass2, runs, set(sample)) for e in manifest.values()],
    }
    if with_rerun:
        summary["rerun"] = _rerun_section(paths, runs, sample, labelled, scenes, pass1, pass2)
    write_json(paths.results / "summary.json", summary)
    (paths.results / "eval.md").write_text(render_markdown(summary), encoding="utf-8")
    return summary


def _score(runs: dict, sample: list[str], labelled: list[str], scenes: list[str], pass1: dict,
           pass2: dict) -> tuple[dict[str, Any], dict[str, int]]:
    """Per-mode agreement, matrices, bad fixes, cost and latency, and the paired counts."""
    modes = {}
    for mode in MODES:
        rows = runs[mode]
        scored = [s for s in labelled if s in rows]
        matrix = {label: {o: 0 for o in OUTCOMES} for label in sorted({pass1[s] for s in scored}, key=_label_order)}
        for s in scored:
            matrix[pass1[s]][rows[s]["outcome"]] += 1
        sampled_rows = [rows[s] for s in sample if s in rows]
        proofs = {r["fixed_sha256"] for r in sampled_rows if _sendable(r)}
        unacceptable = sum(1 for p in proofs if pass2.get(p) == "unacceptable")
        damaged = sum(1 for r in sampled_rows if r.get("damaged"))
        shaped = [rows[s] for s in scenes if s in rows and _sendable(rows[s]) and rows[s].get("shape") == "rounded_rect"]
        all_rows = list(rows.values())
        agree = sum(rows[s]["outcome"] == PREREG_MAPPING[pass1[s]] for s in scored)
        modes[mode] = {
            "n_runs": len(all_rows),
            "n_scored": len(scored),
            "agree": agree,
            "agree_rate": round(agree / len(scored), 3) if scored else None,
            "agree_scene_as_person": sum(rows[s]["outcome"] == SCENE_AS_PERSON[pass1[s]] for s in scored),
            # post hoc, exploratory: only "does a person need to look?" (needs_person vs not)
            "two_class": {name: sum((rows[s]["outcome"] == "needs_person") == (mapping[pass1[s]] == "needs_person")
                                    for s in scored)
                          for name, mapping in (("prereg", PREREG_MAPPING), ("scene_as_person", SCENE_AS_PERSON))},
            "matrix": matrix,  # rows: Ebin's pass-1 label, columns: this mode's outcome
            "outcomes": dict(Counter(r["outcome"] for r in all_rows)),
            "shapes": dict(Counter(r.get("shape") or "die_cut" for r in all_rows)),
            "proofs_to_label": len(proofs),
            "proofs_unlabelled": sum(1 for p in proofs if p not in pass2),
            "unacceptable": unacceptable,
            "damaged": damaged,
            "bad_fixes": unacceptable + damaged,
            "scene_shaped_proofs": len(shaped),
            "scene_shaped_accepted": sum(1 for r in shaped if pass2.get(r["fixed_sha256"]) == "acceptable"),
            "cost_usd": _stats([r["cost_usd"] for r in all_rows]),
            "elapsed_s": _stats([r["elapsed_s"] for r in all_rows]),
        }
    both = [s for s in labelled if all(s in runs[m] for m in MODES)]
    right = {m: {s for s in both if runs[m][s]["outcome"] == PREREG_MAPPING[pass1[s]]} for m in MODES}
    paired = {
        "n": len(both),
        "both_agree": len(right["rules"] & right["agent"]),
        "only_rules_agrees": len(right["rules"] - right["agent"]),
        "only_agent_agrees": len(right["agent"] - right["rules"]),
        "neither": len(set(both) - right["rules"] - right["agent"]),
    }
    return modes, paired


def _rerun_section(paths: Paths, runs: dict, sample: list[str], labelled: list[str], scenes: list[str],
                   pass1: dict, pass2: dict) -> dict[str, Any]:
    """The same numbers with each listed run replaced by its final rerun row (where there is one)."""
    from printready.realset.rerun import RerunError, read_list, rerun_root, rerun_runs

    try:
        listed = read_list(paths)[1]
    except RerunError:
        listed = {m: [] for m in MODES}
    attempts = read_jsonl(rerun_root(paths) / "attempts.jsonl")
    reruns = {m: last_by(read_jsonl(rerun_runs(paths, m)), "image") for m in MODES}
    merged = {m: {**runs[m], **reruns[m]} for m in MODES}
    modes, paired = _score(merged, sample, labelled, scenes, pass1, pass2)
    counts = {
        m: {
            "listed": len(listed[m]),
            "attempts": sum(1 for a in attempts if a["mode"] == m),
            "settled": sum(1 for r in reruns[m].values() if r.get("rerun_final") != "deadline"),
            "error_at_deadline": sum(1 for r in reruns[m].values() if r.get("rerun_final") == "deadline"),
            "still_pending": len([s for s in listed[m] if s not in reruns[m]]),
            "fixed_matches_original": sum(1 for r in reruns[m].values() if r.get("fixed_matches_original") is True),
            "fixed_differs": sum(1 for r in reruns[m].values() if r.get("fixed_matches_original") is False),
        }
        for m in MODES
    }
    return {"label": RERUN_LABEL, "reruns": counts, "modes": modes, "paired": paired,
            "verdict": _verdict(sample, labelled, modes, paired)}


def _sendable(row: dict[str, Any]) -> bool:
    """A proof that would go to the customer: outcome ready or fixable, with a fixed.png."""
    return row["outcome"] != "needs_person" and bool(row.get("fixed_sha256"))


def _label_order(label: str) -> int:
    return PASS1_LABELS.index(label) if label in PASS1_LABELS else len(PASS1_LABELS)


def _verdict(sample: list[str], labelled: list[str], modes: dict[str, Any], paired: dict[str, int]) -> dict[str, Any]:
    rule = (f"agent becomes the default only if it agrees with Ebin on at least {KEEP_MARGIN} more of the "
            "labelled images than rules mode and has no more bad fixes (unacceptable or damaged)")
    missing = []
    if not sample or len(labelled) < len(sample):
        missing.append(f"pass-1 labels {len(labelled)}/{len(sample)}")
    for mode in MODES:
        if modes[mode]["n_scored"] < len(labelled) or not labelled:
            missing.append(f"{mode} runs on {modes[mode]['n_scored']}/{len(labelled)} labelled images")
        if modes[mode]["proofs_unlabelled"]:
            missing.append(f"{modes[mode]['proofs_unlabelled']} {mode} proofs without a pass-2 label")
    margin = modes["agent"]["agree"] - modes["rules"]["agree"]
    if missing:
        return {"status": "pending", "rule": rule, "reason": "; ".join(missing), "agent_minus_rules": margin}
    keep = margin >= KEEP_MARGIN and modes["agent"]["bad_fixes"] <= modes["rules"]["bad_fixes"]
    reason = (f"agent agrees on {modes['agent']['agree']}, rules on {modes['rules']['agree']} (margin {margin:+d}, "
              f"needs +{KEEP_MARGIN}); bad fixes agent {modes['agent']['bad_fixes']}, rules {modes['rules']['bad_fixes']}; "
              f"discordant pairs: only agent right {paired['only_agent_agrees']}, only rules right {paired['only_rules_agrees']}")
    return {"status": "keep_agent" if keep else "keep_rules", "rule": rule, "reason": reason, "agent_minus_rules": margin}


def _card(e: dict[str, Any], pass1: dict, pass2: dict, runs: dict, sample: set) -> dict[str, Any]:
    card: dict[str, Any] = {"image": e["sha256"], "prompt_id": e["prompt_id"], "image_model": e["model"],
                            "file": e["file"], "sampled": e["sha256"] in sample, "label": pass1.get(e["sha256"])}
    for mode in MODES:
        row = runs[mode].get(e["sha256"])
        card[mode] = None if row is None else {
            "outcome": row["outcome"], "shape": row.get("shape") or "die_cut", "handoff_reason": row["handoff_reason"],
            "out_dir": row["out_dir"], "proof_label": pass2.get(row.get("fixed_sha256")),
            "damaged": row.get("damaged", False),
        }
    return card


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0, "total": 0.0, "mean": 0.0, "median": 0.0, "max": 0.0}
    return {"n": len(values), "total": round(sum(values), 4), "mean": round(statistics.fmean(values), 4),
            "median": round(statistics.median(values), 4), "max": round(max(values), 4)}


def _mode_table(m: dict[str, Any]) -> list[str]:
    lines = [
        "| mode | agree (scene = fixable, PREREG) | agree (scene = needs person) | runs | unacceptable proofs | damaged "
        "| cost total | cost / image | time / image |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for mode in MODES:
        x = m[mode]
        rate = f" ({x['agree_rate']:.0%})" if x["agree_rate"] is not None else ""
        lines.append(f"| {mode} | {x['agree']}/{x['n_scored']}{rate} | {x['agree_scene_as_person']}/{x['n_scored']} | "
                     f"{x['n_runs']} | {x['unacceptable']} | {x['damaged']} | ${x['cost_usd']['total']:.4f} | "
                     f"${x['cost_usd']['mean']:.4f} | {x['elapsed_s']['mean']:.1f} s |")
    return lines


def _paired_line(p: dict[str, int]) -> str:
    return (f"Paired on {p['n']} images (PREREG mapping): both agree {p['both_agree']}, only rules "
            f"{p['only_rules_agrees']}, only agent {p['only_agent_agrees']}, neither {p['neither']}.")


def render_markdown(s: dict[str, Any]) -> str:
    m, v = s["modes"], s["verdict"]
    shaped = "; ".join(f"{mode} {m[mode]['scene_shaped_accepted']} of {m[mode]['scene_shaped_proofs']}" for mode in MODES)
    lines = [
        f"# Real set ({s['split']}): rules vs agent vs Ebin",
        "",
        f"{s['n_images']} images; {s['sample']['labelled_pass1']} of {s['sample']['n']} sampled images labelled (pass 1).",
        "Ebin's pass-1 labels: " + ", ".join(f"{k} {s['labels']['pass1'].get(k, 0)}" for k in PASS1_LABELS) + ".",
        f"{s['sample']['scenes']} scenes; shaped-sticker proofs accepted: {shaped}.",
        "",
        "## Preregistered" if "rerun" in s else "",
        "",
        f"**Verdict: {v['status']}.** {v['reason']}",
        f"Rule (PREREG): {v['rule']}.",
        "",
        *_mode_table(m),
        "",
        _paired_line(s["paired"]),
        "",
    ]
    for mode in MODES:
        lines += [f"**{mode}** (rows: Ebin's label, columns: {mode} outcome)", "", "| | " + " | ".join(OUTCOMES) + " |",
                  "|---|" + "---|" * len(OUTCOMES)]
        for label, counts in m[mode]["matrix"].items():
            lines.append(f"| {label} | " + " | ".join(str(counts[o]) for o in OUTCOMES) + " |")
        lines.append("")
    lines += ["Rules mode on every image, by image model:", "", "| image model | " + " | ".join(OUTCOMES) + " |",
              "|---|" + "---|" * len(OUTCOMES)]
    for model, counts in sorted(s["rules_by_image_model"].items()):
        lines.append(f"| {model} | " + " | ".join(str(counts[o]) for o in OUTCOMES) + " |")
    views = [("preregistered", m)]
    if "rerun" in s:
        r = s["rerun"]
        rv = r["verdict"]
        reruns = "; ".join(f"{mode}: {c['listed']} listed, {c['attempts']} attempts, {c['settled']} settled, "
                           f"{c['error_at_deadline']} error at deadline, {c['still_pending']} pending"
                           + (f", fixed.png same as the original {c['fixed_matches_original']}, differs {c['fixed_differs']}"
                              if mode == "rules" else "")
                           for mode, c in r["reruns"].items())
        lines += ["", f"## {r['label'][0].upper()}{r['label'][1:]}", "",
                  "Runs whose every model call returned HTTP 403 or 429 with zero tokens, re-attempted with the "
                  f"same client, prompts and models; each replaced by its final rerun. {reruns}.", "",
                  f"**Verdict ({r['label']}): {rv['status']}.** {rv['reason']}", "",
                  *_mode_table(r["modes"]), "", _paired_line(r["paired"])]
        views.append((r["label"], r["modes"]))
    lines += ["", "## Two-class view (post hoc, exploratory): does a person need to look?", "",
              "| numbers | mode | agree (scene = no person, PREREG) | agree (scene = person) |", "|---|---|---|---|"]
    for name, mm in views:
        for mode in MODES:
            x = mm[mode]
            lines.append(f"| {name} | {mode} | {x['two_class']['prereg']}/{x['n_scored']} | "
                         f"{x['two_class']['scene_as_person']}/{x['n_scored']} |")
    return "\n".join(lines) + "\n"
