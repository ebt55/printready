"""`realset eval`: agreement with Ebin's labels, bad fixes, cost and latency, and the PREREG
keep-or-remove verdict. Writes results/realset/<split>/eval.md and summary.json (the UI's
Results screen reads summary.json).

Keep-or-remove (PREREG 4): agent mode becomes the default only if, on the labelled images, it
agrees with Ebin's pass-1 outcome on at least KEEP_MARGIN more images than rules mode AND it has
no more bad fixes (pass-2 unacceptable, or damaged) than rules mode. Until every sampled image has
a pass-1 label, both modes have run on all of them, and every pass-2 proof is labelled, the
verdict is "pending".
"""

from __future__ import annotations

import json
import statistics
import time
from collections import Counter
from typing import Any

from printready.realset import MODES, Paths, last_by, read_jsonl, sample_shas, write_json
from printready.realset.label import labels_by_pass
from printready.types import OUTCOMES

KEEP_MARGIN = 5


def evaluate(paths: Paths) -> dict[str, Any]:
    manifest = last_by(read_jsonl(paths.manifest), "sha256")
    sample = sample_shas(list(manifest.values()))
    pass1, pass2 = labels_by_pass(paths.labels)
    mapping = _read_json(paths.data / "label-pass2-mapping.json", {})
    runs = {m: last_by(read_jsonl(paths.runs(m)), "image") for m in MODES}
    labelled = [s for s in sample if s in pass1]

    modes = {}
    for mode in MODES:
        rows = runs[mode]
        scored = [s for s in labelled if s in rows]
        matrix = {e: {o: 0 for o in OUTCOMES} for e in OUTCOMES}
        for s in scored:
            matrix[pass1[s]][rows[s]["outcome"]] += 1
        sampled_rows = [rows[s] for s in sample if s in rows]
        proofs = {r["fixed_sha256"] for r in sampled_rows if r["outcome"] != "needs_person" and r.get("fixed_sha256")}
        unacceptable = sum(1 for p in proofs if pass2.get(p) == "unacceptable")
        damaged = sum(1 for r in sampled_rows if r.get("damaged"))
        all_rows = list(rows.values())
        modes[mode] = {
            "n_runs": len(all_rows),
            "n_scored": len(scored),
            "agree": sum(rows[s]["outcome"] == pass1[s] for s in scored),
            "matrix": matrix,  # rows: Ebin's label, columns: this mode's outcome
            "outcomes": dict(Counter(r["outcome"] for r in all_rows)),
            "proofs_to_label": len(proofs),
            "proofs_unlabelled": sum(1 for p in proofs if p not in pass2),
            "unacceptable": unacceptable,
            "damaged": damaged,
            "bad_fixes": unacceptable + damaged,
            "cost_usd": _stats([r["cost_usd"] for r in all_rows]),
            "elapsed_s": _stats([r["elapsed_s"] for r in all_rows]),
        }
        modes[mode]["agree_rate"] = round(modes[mode]["agree"] / len(scored), 3) if scored else None

    both = [s for s in labelled if all(s in runs[m] for m in MODES)]
    right = {m: {s for s in both if runs[m][s]["outcome"] == pass1[s]} for m in MODES}
    paired = {
        "n": len(both),
        "both_agree": len(right["rules"] & right["agent"]),
        "only_rules_agrees": len(right["rules"] - right["agent"]),
        "only_agent_agrees": len(right["agent"] - right["rules"]),
        "neither": len(set(both) - right["rules"] - right["agent"]),
    }
    by_model: dict[str, dict[str, int]] = {}
    for row in runs["rules"].values():
        counts = by_model.setdefault(row["image_model"], {o: 0 for o in OUTCOMES})
        counts[row["outcome"]] += 1

    summary = {
        "split": paths.split,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_images": len(manifest),
        "sample": {"n": len(sample), "labelled_pass1": len(labelled)},
        "labels": {
            "pass1": dict(Counter(pass1[s] for s in labelled)),
            "pass2": dict(Counter(pass2.values())),
        },
        "modes": modes,
        "paired": paired,
        "verdict": _verdict(sample, labelled, modes, paired),
        "rules_by_image_model": by_model,
        "images": [_card(e, pass1, pass2, runs, mapping, set(sample)) for e in manifest.values()],
    }
    write_json(paths.results / "summary.json", summary)
    (paths.results / "eval.md").write_text(render_markdown(summary), encoding="utf-8")
    return summary


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


def _card(e: dict[str, Any], pass1: dict, pass2: dict, runs: dict, mapping: dict, sample: set) -> dict[str, Any]:
    card: dict[str, Any] = {"image": e["sha256"], "prompt_id": e["prompt_id"], "image_model": e["model"],
                            "file": e["file"], "sampled": e["sha256"] in sample, "label": pass1.get(e["sha256"])}
    for mode in MODES:
        row = runs[mode].get(e["sha256"])
        card[mode] = None if row is None else {
            "outcome": row["outcome"], "handoff_reason": row["handoff_reason"], "out_dir": row["out_dir"],
            "proof_label": pass2.get(row.get("fixed_sha256")), "damaged": row.get("damaged", False),
        }
    return card


def _stats(values: list[float]) -> dict[str, float]:
    if not values:
        return {"n": 0, "total": 0.0, "mean": 0.0, "median": 0.0, "max": 0.0}
    return {"n": len(values), "total": round(sum(values), 4), "mean": round(statistics.fmean(values), 4),
            "median": round(statistics.median(values), 4), "max": round(max(values), 4)}


def _read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def render_markdown(s: dict[str, Any]) -> str:
    m, v = s["modes"], s["verdict"]
    lines = [
        f"# Real set ({s['split']}): rules vs agent vs Ebin",
        "",
        f"{s['n_images']} images; {s['sample']['labelled_pass1']} of {s['sample']['n']} sampled images labelled (pass 1).",
        "",
        f"**Verdict: {v['status']}.** {v['reason']}",
        f"Rule (PREREG): {v['rule']}.",
        "",
        "Ebin's pass-1 labels: " + ", ".join(f"{o} {s['labels']['pass1'].get(o, 0)}" for o in OUTCOMES),
        "",
        "| mode | agree with Ebin | runs | unacceptable proofs | damaged | cost total | cost / image | time / image |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for mode in MODES:
        x = m[mode]
        rate = f" ({x['agree_rate']:.0%})" if x["agree_rate"] is not None else ""
        lines.append(f"| {mode} | {x['agree']}/{x['n_scored']}{rate} | {x['n_runs']} | {x['unacceptable']} | "
                     f"{x['damaged']} | ${x['cost_usd']['total']:.4f} | ${x['cost_usd']['mean']:.4f} | "
                     f"{x['elapsed_s']['mean']:.1f} s |")
    p = s["paired"]
    lines += ["", f"Paired on {p['n']} images: both agree {p['both_agree']}, only rules {p['only_rules_agrees']}, "
                  f"only agent {p['only_agent_agrees']}, neither {p['neither']}.", ""]
    for mode in MODES:
        lines += [f"**{mode}** (rows: Ebin, columns: {mode})", "", "| | " + " | ".join(OUTCOMES) + " |",
                  "|---|" + "---|" * len(OUTCOMES)]
        for e in OUTCOMES:
            lines.append(f"| {e} | " + " | ".join(str(m[mode]["matrix"][e][o]) for o in OUTCOMES) + " |")
        lines.append("")
    lines += ["Rules mode on every image, by image model:", "", "| image model | " + " | ".join(OUTCOMES) + " |",
              "|---|" + "---|" * len(OUTCOMES)]
    for model, counts in sorted(s["rules_by_image_model"].items()):
        lines.append(f"| {model} | " + " | ".join(str(counts[o]) for o in OUTCOMES) + " |")
    return "\n".join(lines) + "\n"
