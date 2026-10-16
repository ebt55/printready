"""POST HOC, EXPLORATORY analysis of the real-set test split. Decided after Ebin's pass-1 labels
were in; nothing here is preregistered and nothing here changes the PREREG verdict.

Reads committed results and labels only (no API calls, no edits under src/):
    data/realset/<split>/{manifest,labels}.jsonl, label-pass2.json
    results/realset/<split>/<mode>/runs.jsonl            the preregistered runs
    results/realset/<split>-rerun/<mode>/runs.jsonl      the PREREG addendum 1 reruns
    results/realset/<split>-rerun/attempts.jsonl

1. Integrity checks to run BEFORE pass 2 (PASS/FAIL; exit 1 on any FAIL):
   (a) every billed rerun attempt has its runs.jsonl row;
   (b) runs with the same fixed.png sha256 have byte-identical proof.png, so pass 2's dedupe by
       fixed hash is a dedupe by the proof Ebin sees;
   (c) the pass-2 list the label page receives carries no mode, model or source information.
2. Post-hoc views, original runs and reruns side by side, written to
   results/realset/<split>/posthoc.md.

    uv run python analysis/posthoc.py [--split test] [--build-pass2]

--build-pass2 first writes the pass-2 list with the frozen `printready.realset.label.pass2_items`
(what `printready realset label --pass 2` writes), if it is not there yet.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from PIL import Image

from printready.realset import MODES, Paths, last_by, read_jsonl, sample_shas
from printready.realset.rerun import rerun_root, rerun_runs

SEED = 7
OUTCOMES = ("ready", "fixable", "needs_person")
PRODUCTS = ("die_cut", "rounded_rect", "needs_person")
PRODUCT_OF_LABEL = {"ready_diecut": "die_cut", "fixable_diecut": "die_cut", "scene": "rounded_rect",
                    "needs_person": "needs_person"}
PERSON = {"prereg (scene = no person)": {"needs_person"}, "scene = person": {"needs_person", "scene"}}
BLIND_LEAKS = re.compile(r"rules|agent|grok|xai|imagine|rerun|original|mode|model", re.IGNORECASE)
PAGE_KEYS = {"pass", "caption", "keys", "labels", "items"}
ITEM_KEYS = {"image", "proof", "file"}
HASH_FILE = re.compile(r"^label-images/[0-9a-f]{64}\.png$")


# ---------------------------------------------------------------- data

class Data:
    """Everything the checks and views read, loaded once."""

    def __init__(self, paths: Paths) -> None:
        self.paths = paths
        self.manifest = last_by(read_jsonl(paths.manifest), "sha256")
        self.sample = sample_shas(list(self.manifest.values()))
        labels = read_jsonl(paths.labels)
        self.pass1 = {r["image"]: r["label"] for r in labels if r.get("pass") == 1}
        self.labelled = [s for s in self.sample if s in self.pass1]
        self.original = {m: last_by(read_jsonl(paths.runs(m)), "image") for m in MODES}
        self.rerun = {m: last_by(read_jsonl(rerun_runs(paths, m)), "image") for m in MODES}
        self.rerun_rows = {m: read_jsonl(rerun_runs(paths, m)) for m in MODES}
        self.attempts = read_jsonl(rerun_root(paths) / "attempts.jsonl")
        self.views = {"original runs": self.original,
                      "with reruns": {m: {**self.original[m], **self.rerun[m]} for m in MODES}}


def _sendable(row: dict[str, Any]) -> bool:
    return row["outcome"] != "needs_person" and bool(row.get("fixed_sha256"))


# ---------------------------------------------------------------- 1. integrity

def check_attempts(d: Data) -> tuple[bool, str]:
    rows = {(m, r["image"], r.get("attempt")) for m in MODES for r in d.rerun_rows[m]}
    billed = [a for a in d.attempts if a.get("billed")]
    missing = [a for a in billed if (a["mode"], a["image"], a["attempt"]) not in rows]
    msg = f"{len(billed)} billed attempts, {len(missing)} without a runs.jsonl row"
    if missing:
        msg += ": " + ", ".join(f"{a['mode']} {a['image'][:12]} #{a['attempt']}" for a in missing[:5])
    return not missing, msg


def check_proofs(d: Data) -> tuple[bool, str]:
    """Pass-2 candidates (sampled, sendable) from original runs and reruns, grouped by fixed hash."""
    groups: dict[str, set[bytes]] = {}
    sampled = set(d.sample)
    for runs in (d.original, d.rerun):
        for mode in MODES:
            for row in runs[mode].values():
                if row["image"] in sampled and _sendable(row):
                    proof = d.paths.root / row["out_dir"] / "proof.png"
                    groups.setdefault(row["fixed_sha256"], set()).add(proof.read_bytes() if proof.exists() else b"")
    bad = [h for h, proofs in groups.items() if len(proofs) != 1 or b"" in proofs]
    return not bad, (f"{len(groups)} fixed.png groups, {sum(len(p) == 1 for p in groups.values())} with one proof"
                     + (f"; differing or missing proofs in {', '.join(h[:12] for h in bad[:5])}" if bad else ""))


def check_pass2_blind(d: Data) -> tuple[bool, str]:
    path = d.paths.data / "label-pass2.json"
    if not path.exists():
        return False, f"{path.name} is not built yet (run with --build-pass2)"
    text = path.read_text(encoding="utf-8")
    page = json.loads(text)
    problems = []
    if set(page) != PAGE_KEYS:
        problems.append(f"page keys {sorted(set(page) - PAGE_KEYS)}")
    for item in page["items"]:
        if set(item) != ITEM_KEYS:
            problems.append(f"item keys {sorted(set(item) - ITEM_KEYS)}")
        if not HASH_FILE.match(item["file"]):
            problems.append(f"file {item['file']!r}")
        png = d.paths.data / item["file"]
        if not png.exists():
            problems.append(f"missing {item['file']}")
            continue
        with Image.open(png) as im:
            meta = " ".join(f"{k} {v}" for k, v in im.info.items() if isinstance(v, (str, bytes)))
        if BLIND_LEAKS.search(meta):
            problems.append(f"PNG metadata in {item['file']}")
    leak = BLIND_LEAKS.search(text)
    if leak:
        problems.append(f"the page text contains {leak.group(0)!r}")
    return not problems, f"{len(page['items'])} items" + (f"; {'; '.join(problems[:5])}" if problems else ", no mode/model/source")


# ---------------------------------------------------------------- 2. views

def product_of_run(row: dict[str, Any]) -> str:
    return "needs_person" if row["outcome"] == "needs_person" else (row.get("shape") or "die_cut")


def product_view(d: Data, runs: dict) -> dict[str, Any]:
    out = {}
    for mode in MODES:
        scored = [s for s in d.labelled if s in runs[mode]]
        matrix = {p: {q: 0 for q in PRODUCTS} for p in PRODUCTS}
        for s in scored:
            matrix[PRODUCT_OF_LABEL[d.pass1[s]]][product_of_run(runs[mode][s])] += 1
        out[mode] = {"n": len(scored), "agree": sum(matrix[p][p] for p in PRODUCTS), "matrix": matrix}
    return out


def two_class_view(d: Data, runs: dict) -> dict[str, dict[str, int]]:
    return {mode: {name: sum((runs[mode][s]["outcome"] == "needs_person") == (d.pass1[s] in person)
                             for s in d.labelled if s in runs[mode])
                   for name, person in PERSON.items()} | {"n": sum(s in runs[mode] for s in d.labelled)}
            for mode in MODES}


def ceiling(d: Data) -> dict[str, Any]:
    ready_labels = sum(d.pass1[s] == "ready_diecut" for s in d.labelled)
    opaque = sum(e.get("format") == "JPEG" for e in d.manifest.values())
    ready_outputs = sum(r["outcome"] == "ready" for runs in d.views.values() for m in MODES for r in runs[m].values())
    return {"labelled": len(d.labelled), "ready_labels": ready_labels, "ceiling": len(d.labelled) - ready_labels,
            "images": len(d.manifest), "opaque_jpeg": opaque, "ready_outputs": ready_outputs}


def handoff_reason(row: dict[str, Any]) -> str | None:
    """Why a run ended needing a person: the loop's own stops, the model's choice, or a rule."""
    if row["outcome"] != "needs_person":
        return None
    reason = row.get("handoff_reason")
    if reason in ("error", "turn limit", "budget"):
        return reason
    if reason:
        return "model choice"
    if any(v["status"] == "skip" for k, v in row["after"].items() if k.startswith("text_")):
        return "error"  # rules mode: the vision call failed
    return "rule: " + ", ".join(sorted(k for k, v in row["after"].items() if v["status"] in ("warn", "fail", "skip")
                                       and v["fixer"] in ("person", "none", "auto")))


def handoffs(d: Data, runs: dict) -> dict[str, Counter]:
    sampled = set(d.sample)
    return {m: Counter(r for row in runs[m].values() if row["image"] in sampled and (r := handoff_reason(row)))
            for m in MODES}


def messages(d: Data, runs: dict, n: int = 3, seed: int = SEED) -> list[dict[str, str]]:
    both = sorted(s for s in d.labelled if all(s in runs[m] and _sendable(runs[m][s]) for m in MODES))
    picks = random.Random(seed).sample(both, min(n, len(both)))
    return [{"image": s, "prompt_id": d.manifest[s]["prompt_id"], "label": d.pass1[s],
             **{m: runs[m][s]["customer_message"] for m in MODES}} for s in picks]


# ---------------------------------------------------------------- report

def render(d: Data, checks: list[tuple[str, bool, str]]) -> str:
    c = ceiling(d)
    lines = [
        f"# Real set ({d.paths.split}): post-hoc views",
        "",
        "**Post hoc, exploratory.** Decided after Ebin's pass-1 labels were in. Nothing on this page is "
        "preregistered or changes the PREREG verdict (see eval.md). \"with reruns\" = the preregistered runs with "
        "the PREREG addendum 1 reruns in place of the runs that never reached a model.",
        "",
        "## Integrity checks (before pass 2)",
        "",
        *[f"- {'PASS' if ok else 'FAIL'} {name}: {msg}" for name, ok, msg in checks],
        "",
        "## The ceiling (post hoc)",
        "",
        f"All {c['opaque_jpeg']} of {c['images']} generated images are opaque JPEGs, so every run has to remove a "
        "background or change the product, and `outcome()` can never return `ready` "
        f"({c['ready_outputs']} ready outputs in all runs). Ebin labelled {c['ready_labels']} of the {c['labelled']} "
        f"sampled images \"ready as a die-cut\", so under the PREREG mapping no mode can agree on more than "
        f"**{c['ceiling']} of {c['labelled']}**.",
        "",
    ]
    for view, runs in d.views.items():
        pv, tc, ho = product_view(d, runs), two_class_view(d, runs), handoffs(d, runs)
        lines += [f"## {view[0].upper()}{view[1:]}", "",
                  "Product agreement (post hoc): Ebin's ready/fixable die-cut -> die_cut, scene -> rounded_rect, "
                  "needs a person -> needs_person; a run's product is its shape unless it needs a person.", "",
                  "| mode | agree | " + " | ".join(f"Ebin {p}: {' / '.join(PRODUCTS)}" for p in PRODUCTS) + " |",
                  "|---|---|" + "---|" * len(PRODUCTS)]
        for mode in MODES:
            x = pv[mode]
            cells = [" / ".join(str(x["matrix"][p][q]) for q in PRODUCTS) for p in PRODUCTS]
            lines.append(f"| {mode} | {x['agree']}/{x['n']} | " + " | ".join(cells) + " |")
        lines += ["", "Two-class view (post hoc): does a person need to look?", "",
                  "| mode | " + " | ".join(PERSON) + " |", "|---|" + "---|" * len(PERSON)]
        for mode in MODES:
            lines.append(f"| {mode} | " + " | ".join(f"{tc[mode][k]}/{tc[mode]['n']}" for k in PERSON) + " |")
        lines += ["", "Why runs on the sampled images needed a person (post hoc):", "",
                  "| mode | reasons |", "|---|---|"]
        for mode in MODES:
            lines.append(f"| {mode} | " + (", ".join(f"{k} {v}" for k, v in ho[mode].most_common()) or "none") + " |")
        lines.append("")
    lines += ["## Customer messages, same images (post hoc)", "",
              f"Three sampled images where both modes would send a proof, picked with seed {SEED}, with reruns.", ""]
    for m in messages(d, d.views["with reruns"]):
        lines += [f"**{m['prompt_id']}** (Ebin: {m['label']})", "",
                  f"- rules (template): {m['rules']}", f"- agent (model): {m['agent']}", ""]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Post-hoc, exploratory views of the real-set test split.")
    ap.add_argument("--split", default="test")
    ap.add_argument("--root", type=Path, default=None, help="repo root (default: this checkout)")
    ap.add_argument("--build-pass2", action="store_true", help="write the pass-2 list first if it is missing")
    args = ap.parse_args(argv)
    paths = Paths.for_split(args.split, args.root)
    if args.build_pass2 and not (paths.data / "label-pass2.json").exists():
        from printready.realset.label import pass2_items

        print(f"built the pass-2 list: {len(pass2_items(paths)['items'])} proofs")
    d = Data(paths)
    checks = [("(a) billed attempts have rows", *check_attempts(d)),
              ("(b) one proof per fixed.png", *check_proofs(d)),
              ("(c) pass-2 list is blind", *check_pass2_blind(d))]
    for name, ok, msg in checks:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {msg}")
    out = paths.results / "posthoc.md"
    out.write_text(render(d, checks), encoding="utf-8")
    print(f"wrote {out}")
    return 0 if all(ok for _, ok, _ in checks) else 1


if __name__ == "__main__":
    sys.exit(main())
