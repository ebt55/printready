"""Readers for the Results screen, over the layouts the bench and real-set chunks write.

    results/bench/<split>/metrics.json             `printready bench report`
    data/realset/<split>/manifest.jsonl            one line per generated image (sha256, file, model, prompt)
    data/realset/<split>/labels.jsonl              Ebin's labels (pass 1 by image, pass 2 by proof = fixed.png sha)
    results/realset/<split>/<mode>/runs.jsonl      one summary row per image run (outcome, out_dir, ...)
    results/realset/<split>/<mode>/<sha256>/       that run's outputs (report.json, proof.png, ...)
    results/realset/<split>/summary.json           `printready realset eval`: cards, agreement, verdict

Sources are searched in order: the repo first, then (in --demo) the demo folder, which mirrors the
same layout and is always labelled demo. A real benchmark always wins over the demo numbers.
Everything missing becomes an empty state, never an error.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from printready.web.paths import safe_child
from printready.web.runs import build_view, make_thumb

BENCH_SPLITS = ("dev", "test")
MODES = ("rules", "agent")
# Blinding: the test split's images, runs and labels stay out of the workbench until Ebin's pass 2
# is done. Only `serve --show-test` or an explicit `site build --realset results/realset/test`
# shows them.
BLIND_SPLITS = ("test",)


@dataclass(frozen=True)
class Source:
    root: Path
    demo: bool = False
    show_blind: bool = False  # True only when the caller explicitly unblinds the test split


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


# ------------------------------------------------------------------ benchmark

def bench_splits(sources: list[Source]) -> list[dict]:
    """Splits with metrics. If any real split exists, demo numbers are never offered."""
    for want_demo in (False, True):
        found = [{"split": s, "demo": src.demo} for src in sources if src.demo == want_demo
                 for s in BENCH_SPLITS if (src.root / "results" / "bench" / s / "metrics.json").exists()]
        if found:
            seen, out = set(), []
            for f in found:
                if f["split"] not in seen:
                    seen.add(f["split"])
                    out.append(f)
            return out
    return []


def bench_metrics(sources: list[Source], split: str) -> dict:
    if split not in BENCH_SPLITS:
        return {"available": False, "split": split, "reason": f"unknown split {split!r}"}
    offered = {b["split"]: b["demo"] for b in bench_splits(sources)}
    for src in sources:
        if split in offered and src.demo != offered[split]:
            continue
        data = _read_json(src.root / "results" / "bench" / split / "metrics.json")
        if isinstance(data, dict):
            return {**data, "available": True, "split": split, "demo": src.demo or bool(data.get("demo"))}
    return {"available": False, "split": split,
            "reason": f"No benchmark results for the {split} split yet. Run `printready bench run --split {split}` "
                      f"then `printready bench report --split {split}`."}


# ------------------------------------------------------------------ real set

def _split_dirs(src: Source) -> list[Path]:
    base = src.root / "results" / "realset"
    if not base.is_dir():
        return []
    out = []
    for d in sorted(base.iterdir()):
        if d.name in BLIND_SPLITS and not src.show_blind:
            continue
        if d.is_dir() and ((d / "summary.json").exists() or any((d / m / "runs.jsonl").exists() for m in MODES)):
            out.append(d)
    return out


def realset_runs(sources: list[Source]) -> list[dict]:
    out, seen = [], set()
    for src in sources:
        for d in _split_dirs(src):
            if d.name in seen:
                continue
            seen.add(d.name)
            n = len(_read_jsonl(src.root / "data" / "realset" / d.name / "manifest.jsonl"))
            out.append({"id": d.name, "demo": src.demo, "n": n, "has_summary": (d / "summary.json").exists()})
    return out


def realset_source(sources: list[Source], split: str) -> Source | None:
    for src in sources:
        if any(d.name == split for d in _split_dirs(src)):
            return src
    return None


def _labels(path: Path) -> tuple[dict, dict]:
    p1, p2 = {}, {}
    for row in _read_jsonl(path):
        if row.get("pass") == 1:
            p1[row.get("image")] = row.get("label")
        elif row.get("pass") == 2 and row.get("proof"):
            p2[row.get("proof")] = row.get("label")
    return p1, p2


def _cards_raw(src: Source, split: str) -> tuple[list[dict], dict | None, dict]:
    """(cards in summary.json's shape, summary or None, manifest by sha)."""
    data = src.root / "data" / "realset" / split
    res = src.root / "results" / "realset" / split
    manifest = {e.get("sha256"): e for e in _read_jsonl(data / "manifest.jsonl") if e.get("sha256")}
    summary = _read_json(res / "summary.json")
    if isinstance(summary, dict) and isinstance(summary.get("images"), list):
        return summary["images"], summary, manifest
    # Before `realset eval` has run: build the same cards from the run rows and the labels.
    runs = {m: {r.get("image"): r for r in _read_jsonl(res / m / "runs.jsonl")} for m in MODES}
    p1, p2 = _labels(data / "labels.jsonl")
    cards = []
    shas = list(manifest) or sorted(set(runs["rules"]) | set(runs["agent"]))
    for sha in shas:
        e = manifest.get(sha, {})
        card = {"image": sha, "prompt_id": e.get("prompt_id"), "image_model": e.get("model"), "file": e.get("file"),
                "sampled": None, "label": p1.get(sha)}
        for m in MODES:
            row = runs[m].get(sha)
            card[m] = None if row is None else {
                "outcome": row.get("outcome"), "handoff_reason": row.get("handoff_reason"), "out_dir": row.get("out_dir"),
                "proof_label": p2.get(row.get("fixed_sha256")), "damaged": row.get("damaged", False)}
        if card["rules"] or card["agent"]:
            cards.append(card)
    return cards, None, manifest


def realset_payload(sources: list[Source], split: str, thumb_url: Callable[[str], str]) -> dict | None:
    """Gallery cards and the agreement summary for one split. `thumb_url(rel)` takes a path
    relative to the source root (data/realset/... or results/realset/...)."""
    src = realset_source(sources, split)
    if src is None:
        return None
    raw, summary, manifest = _cards_raw(src, split)
    cards, models = [], set()
    for c in raw:
        sha = c.get("image", "")
        e = manifest.get(sha, {})
        file = c.get("file") or e.get("file")
        card = {"image": sha, "short": sha[:10], "image_model": c.get("image_model") or e.get("model"),
                "prompt": e.get("prompt"), "prompt_id": c.get("prompt_id") or e.get("prompt_id"),
                "sampled": c.get("sampled"), "label": c.get("label"),
                "original": thumb_url(f"data/realset/{split}/{file}") if file else None, "modes": {}}
        for m in MODES:
            mc = c.get(m)
            if not mc:
                continue
            out_dir = mc.get("out_dir")
            proof = (src.root / out_dir / "proof.png") if out_dir else None
            card["modes"][m] = {"outcome": mc.get("outcome"), "handoff_reason": mc.get("handoff_reason"),
                                "proof_label": mc.get("proof_label"), "damaged": bool(mc.get("damaged")),
                                "proof": thumb_url(f"{out_dir}/proof.png") if proof and proof.exists() else None}
        models.add(card["image_model"])
        cards.append(card)
    agreement = None
    if summary:
        agreement = {k: v for k, v in summary.items() if k != "images"}
    return {"run": split, "demo": src.demo, "size_in": 3.0, "labeller": "Ebin",
            "image_models": sorted(m for m in models if m), "items": cards, "agreement": agreement}


def resolve_file(sources: list[Source], split: str, rel: str) -> Path | None:
    """A file of this split, by its root-relative path: only under data/realset/<split>/ or
    results/realset/<split>/ (nothing else in the repo is reachable)."""
    src = realset_source(sources, split)
    if src is None:
        return None
    path = safe_child(src.root, rel)
    if path is None or not path.is_file():
        return None
    allowed = [(src.root / "data" / "realset" / split).resolve(), (src.root / "results" / "realset" / split).resolve()]
    return path if any(a in path.parents for a in allowed) else None


def realset_item_view(sources: list[Source], split: str, sha: str, mode: str, file_url: Callable[[str], str]) -> dict | None:
    """A saved real-set run as a read-only RunView. `file_url(rel)` maps a root-relative path."""
    src = realset_source(sources, split)
    if src is None:
        return None
    raw, _, manifest = _cards_raw(src, split)
    card = next((c for c in raw if c.get("image") == sha), None)
    if not card or not card.get(mode) or not card[mode].get("out_dir"):
        return None
    out_rel = card[mode]["out_dir"]
    run_dir = safe_child(src.root, out_rel)
    if run_dir is None or not run_dir.is_dir():
        return None
    events = _read_jsonl(run_dir / "events.jsonl")
    if not events:  # agent runs keep their turns in log.jsonl
        events = [e for e in _read_jsonl(run_dir / "log.jsonl") if e.get("type") == "turn"]
    report = _read_json(run_dir / "report.json")
    if report and not any(e.get("type") == "done" for e in events):
        events.append({"type": "done", "result": report})
    e = manifest.get(sha, {})
    file = card.get("file") or e.get("file")
    original = None
    if file:
        opath = safe_child(src.root, f"data/realset/{split}/{file}")
        if opath and opath.exists():
            original = (opath, file_url(f"data/realset/{split}/{file}"))
    record = {"id": f"{split}/{sha[:12]}/{mode}", "filename": f"{sha[:12]} · {card.get('image_model') or ''}".strip(" ·"),
              "spec": {"product": "die_cut", "size_in": 3.0, "prompt": e.get("prompt")}, "mode": mode,
              "model": (report or {}).get("model") if report else None, "status": "done" if report else "error",
              "error": None if report else "report.json is missing for this run", "demo": src.demo}
    view = build_view(run_dir, record, lambda name: file_url(f"{out_rel}/{name}"), events, original=original,
                      readonly=True)
    modes = [m for m in MODES if card.get(m)]
    view["realset"] = {"run": split, "image": sha, "modes": modes, "image_model": card.get("image_model"),
                       "label": card.get("label"), "prompt": e.get("prompt")}
    return view


def thumb_for(sources: list[Source], split: str, rel: str, cache: Path, max_px: int = 360) -> Path | None:
    src_path = resolve_file(sources, split, rel)
    if src_path is None:
        return None
    st = src_path.stat()
    key = hashlib.sha256(f"{src_path}|{st.st_mtime}|{max_px}".encode()).hexdigest()[:24]
    dest = cache / "thumbs" / f"{key}.png"
    if dest.exists() or make_thumb(src_path, dest, max_px):
        return dest
    return None
