"""`printready bench generate`: plan a split, render every sample, apply the 10 % rule, write the
PNGs (and ground-truth masks for opaque samples) and the manifest.

Determinism: every sample has its own random stream, seeded from (split seed, family, index), so
the output does not depend on worker count or order. PNGs carry no metadata and use a fixed
compression level, so a rerun reproduces every file byte for byte (same Pillow/zlib build).
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from printready.bench import text as txt
from printready.bench.bases import N_BASES, badge_indices
from printready.bench.defects import (
    BACKGROUNDS,
    BUILDERS,
    EDGE_CASES,
    ISLAND_GAPS_IN,
    RESOLUTION_PPI,
    SOFT_RAMPS_IN,
    TEXT_CAP_PT,
    Context,
    PlanItem,
    Planted,
    Resample,
    edge_runs,
)
from printready.bench.labels import (
    Thresholds,
    expected_final,
    expected_outcome,
    labels,
    near_threshold,
)
from printready.profile import load_profile

SEEDS = {"dev": 7, "test": 8}
SIZE_IN = 3.0
PRODUCT = "die_cut"
FAMILY_COUNTS = {
    "clean": 40,
    "resolution": 42,
    "background": 40,
    "islands": 40,
    "soft_alpha": 24,
    "edge_crop": 24,
    "text": 48,
}
FAMILY_STREAMS = {name: k + 1 for k, name in enumerate(FAMILY_COUNTS)}  # 0 is the base designs
PLAN_STREAM = 100
MAX_DRAWS = 40
PNG_COMPRESS_LEVEL = 6


class PreregMissing(RuntimeError):
    """The test split is generated only after PREREG.md is committed."""


# --- the plan -------------------------------------------------------------------------------------


def plan(split: str) -> list[PlanItem]:
    """Every sample of a split with its bases and planted parameters (no rendering)."""
    seed = SEEDS[split]
    items: list[PlanItem] = []

    def add(family: str, i: int, bases: list[int], param: dict[str, Any]) -> None:
        items.append(PlanItem(f"{family}-{i:03d}", family, i, tuple(b % N_BASES for b in bases), param))

    for i in range(FAMILY_COUNTS["clean"]):
        add("clean", i, [i], {})
    for i in range(FAMILY_COUNTS["resolution"]):
        add("resolution", i, [i], {"ppi": RESOLUTION_PPI[i // 7]})
    for i in range(FAMILY_COUNTS["background"]):
        add("background", i, [3 + i], {"background": BACKGROUNDS[i // 8]})
    for i in range(FAMILY_COUNTS["islands"]):
        a = (6 + i) % N_BASES
        add("islands", i, [a, a + 17], {"gap_in": ISLAND_GAPS_IN[i // 8]})
    for i in range(FAMILY_COUNTS["soft_alpha"]):
        style = "shadow" if i % 2 == 0 else "glow"
        add("soft_alpha", i, [11 + i], {"ramp_in": SOFT_RAMPS_IN[i // 8], "style": style})
    for i in range(FAMILY_COUNTS["edge_crop"]):
        add("edge_crop", i, [23 + i], {"case": tuple(EDGE_CASES)[i // 8]})

    rng = np.random.default_rng(np.random.SeedSequence([seed, PLAN_STREAM]))
    words = [str(w) for w in rng.permutation(txt.WORDS)]
    correct, sized = words[:16], words[16:32]
    by_method = {m: [g for g in txt.GARBLES if g[2] == m] for m in ("swap", "double", "drop")}
    garbles = []
    for method, n in (("swap", 6), ("double", 5), ("drop", 5)):
        pool = by_method[method]
        garbles += [pool[k] for k in rng.permutation(len(pool))[:n]]
    garbles = [garbles[k] for k in rng.permutation(len(garbles))]
    badges = badge_indices()
    for i in range(48):
        base = badges[i % len(badges)]
        if i < 16:
            param = {"variant": "correct", "word": correct[i], "intended": correct[i]}
        elif i < 32:
            g = garbles[i - 16]
            param = {"variant": "garbled", "word": g[0], "intended": g[1], "method": g[2]}
        else:
            k = i - 32
            param = {"variant": "sized", "word": sized[k], "intended": sized[k],
                     "cap_pt": TEXT_CAP_PT[k // 4]}
        add("text", i, [base], param)
    return items


def limited(items: list[PlanItem], limit: int | None) -> list[PlanItem]:
    """The first `limit` samples of each family (all of them when limit is None)."""
    if limit is None:
        return items
    seen: Counter[str] = Counter()
    out = []
    for item in items:
        if seen[item.family] < limit:
            out.append(item)
            seen[item.family] += 1
    return out


# --- measuring and building one sample ------------------------------------------------------------


def encode_png(array: np.ndarray) -> bytes:
    """PNG bytes with no metadata (no time, no text chunks) and a fixed compression level."""
    buf = io.BytesIO()
    Image.fromarray(array).save(buf, format="PNG", compress_level=PNG_COMPRESS_LEVEL)
    return buf.getvalue()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def measure(p: Planted, png: bytes, th: Thresholds, size_in: float = SIZE_IN) -> dict[str, Any]:
    """Ground-truth quantities of a planted sample, measured on its own GT mask or taken from its
    construction. These are what the labels and the 10 % rule read."""
    mask = p.subject
    H, W = mask.shape
    rows, cols = np.flatnonzero(mask.any(axis=1)), np.flatnonzero(mask.any(axis=0))
    if rows.size == 0:
        raise RuntimeError("sample has no subject pixels")
    bb = [int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1]
    long_mask = max(bb[2] - bb[0], bb[3] - bb[1])
    if p.analytic_bbox is not None:
        ax0, ay0, ax1, ay1 = p.analytic_bbox
        long_px = max(ax1 - ax0, ay1 - ay0)
        if abs(long_px - long_mask) > 2:  # the drawing and its geometry disagree: a generator bug
            raise RuntimeError(f"analytic bbox long side {long_px:.1f} px vs GT mask {long_mask} px")
        source = "analytic"
    else:
        long_px, source = float(long_mask), "mask"
    printable, one_in = th.printable_in(size_in), th.printable_in(1.0)
    basis = max(H, W) if p.opaque else long_px  # opaque: PPI from the full canvas until removal
    ppi_subject = long_px / printable
    runs = edge_runs(mask)
    run_px = max(runs.values())
    ramp_px = p.gt.get("ramp_px", 1)  # 1 = the one-pixel anti-aliased edge
    gt: dict[str, Any] = {
        "canvas": [W, H],
        "opaque": p.opaque,
        "bbox_px": bb,
        "bbox_long_px": long_px,
        "bbox_source": source,
        "ppi": basis / printable,
        "ppi_at_1in": basis / one_in,
        "ppi_subject": ppi_subject,
        "ppi_subject_at_1in": long_px / one_in,
        "edge_runs_px": runs,
        "edge_run_px": run_px,
        "edge_run_in": run_px / ppi_subject,
        "ramp_px": ramp_px,
        "ramp_in": ramp_px / ppi_subject,
        "parts": p.gt.get("parts", 1),
        "min_side_px": min(H, W),
        "file_bytes": len(png),
    }
    if gt["parts"] > 1:
        gt["gap_px"] = p.gt["gap_px"]
        gt["gap_in"] = p.gt["gap_px"] / ppi_subject
    for key in ("background", "ring_uniformity", "ring_de_max", "bg_de_max", "edge_contrast_de"):
        if key in p.gt:
            gt[key] = p.gt[key]
    if p.gt.get("cap_height_px") is not None:
        cap = p.gt["cap_height_px"]
        gt.update(word=p.gt["word"], cap_height_px=cap, cap_height_pt=txt.px_to_pt(cap, ppi_subject),
                  cap_height_frac=cap / (bb[3] - bb[1]))
    if "garbled" in p.gt:
        gt.update(garbled=p.gt["garbled"], intended=p.gt["intended"])
    return gt


def family_problems(item: PlanItem, gt: dict[str, Any]) -> list[str]:
    """Family-specific conditions on the measured ground truth (beyond the 10 % rule)."""
    problems = []
    if item.family == "edge_crop":
        lo, hi = EDGE_CASES[item.param["case"]]
        if not lo <= gt["edge_run_in"] <= hi:
            problems.append(f"edge run {gt['edge_run_in']:.3f} in is outside {lo}-{hi} in")
    elif gt["edge_run_px"] != 0:
        problems.append("subject touches the canvas edge")
    return problems


@dataclass
class Built:
    planted: Planted
    gt: dict[str, Any]
    png: bytes
    mask_png: bytes | None
    reasons: list[str]


def build(item: PlanItem, seed: int, th: Thresholds) -> Built:
    """Render one sample, redrawing from its seeded stream until it passes the 10 % rule."""
    rng = np.random.default_rng(np.random.SeedSequence([seed, FAMILY_STREAMS[item.family], item.index]))
    reasons: list[str] = []
    for attempt in range(MAX_DRAWS):
        try:
            planted = BUILDERS[item.family](item, rng, Context(seed, th, attempt, SIZE_IN))
        except Resample as exc:
            reasons.append(str(exc))
            continue
        png = encode_png(planted.rgba)
        gt = measure(planted, png, th)
        problems = near_threshold(gt, th) + family_problems(item, gt)
        if problems:
            reasons.append("; ".join(problems))
            continue
        mask_png = encode_png(planted.subject.astype(np.uint8) * 255) if planted.opaque else None
        return Built(planted, gt, png, mask_png, reasons)
    raise RuntimeError(f"{item.id}: no valid sample in {MAX_DRAWS} draws; last: {reasons[-3:]}")


def rounded_json(value: Any, ndigits: int = 4) -> Any:
    if isinstance(value, (float, np.floating)):
        return round(float(value), ndigits)
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, dict):
        return {k: rounded_json(v, ndigits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [rounded_json(v, ndigits) for v in value]
    return value


def manifest_row(item: PlanItem, split: str, built: Built, th: Thresholds) -> dict[str, Any]:
    p, gt = built.planted, built.gt
    vision = item.family == "text"
    final, fixes = expected_final(gt, th)
    row: dict[str, Any] = {
        "id": item.id,
        "family": item.family,
        "param": p.param,
        "spec": {"product": PRODUCT, "size_in": SIZE_IN},
        "image": f"data/bench/{split}/{item.id}.png",
        "mask": f"data/bench/{split}/{item.id}.mask.png" if built.mask_png else None,
        "width": int(p.rgba.shape[1]),
        "height": int(p.rgba.shape[0]),
        "sha256": sha256(built.png),
        "mask_sha256": sha256(built.mask_png) if built.mask_png else None,
        "rgba_sha256": sha256(p.rgba.tobytes()),
        "bases": p.bases,
        "kind": p.kind,
        "expected": labels(gt, th, vision=vision),
        "expected_final": {c: v["status"] for c, v in final.items()},
        "fixes": fixes,
        "outcome": expected_outcome(final, fixes),
    }
    if vision:
        final_v, fixes_v = expected_final(gt, th, vision=True)
        row["outcome_vision"] = expected_outcome(final_v, fixes_v)
    row["gt"] = gt
    row["resamples"] = len(built.reasons)
    row["resample_reasons"] = built.reasons
    return rounded_json(row)


def _generate_one(args: tuple[PlanItem, str, Thresholds, str]) -> dict[str, Any]:
    """Worker: build, write the PNG (and mask), return the manifest row."""
    item, split, th, root = args
    built = build(item, SEEDS[split], th)
    out = Path(root) / "data" / "bench" / split
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{item.id}.png").write_bytes(built.png)
    if built.mask_png:
        (out / f"{item.id}.mask.png").write_bytes(built.mask_png)
    return manifest_row(item, split, built, th)


# --- the split ------------------------------------------------------------------------------------


def prereg_committed(root: Path) -> tuple[bool, str]:
    """True when PREREG.md exists and git has at least one commit touching it (read-only git)."""
    if not (root / "PREREG.md").is_file():
        return False, "PREREG.md does not exist"
    try:
        res = subprocess.run(["git", "log", "--oneline", "--", "PREREG.md"], cwd=root,
                             capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run git: {exc}"
    if res.returncode != 0 or not res.stdout.strip():
        return False, "PREREG.md is not committed (git log --oneline -- PREREG.md is empty)"
    return True, ""


def manifest_path(root: Path, split: str, limit: int | None = None) -> Path:
    suffix = f"-limit{limit}" if limit is not None else ""
    return root / "data" / "bench" / f"manifest-{split}{suffix}.jsonl"


def default_jobs() -> int:
    return max(1, min(8, (os.cpu_count() or 2) - 1))


def generate_split(
    split: str,
    root: Path | str = ".",
    *,
    limit: int | None = None,
    jobs: int | None = None,
    profile_path: Path | None = None,
    sheet: bool | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Generate a split under `root`. A limited run writes `manifest-<split>-limit<N>.jsonl` and
    no contact sheet, so it never overwrites the committed full manifest."""
    if split not in SEEDS:
        raise ValueError(f"unknown split {split!r}; choose from {sorted(SEEDS)}")
    root = Path(root)
    if split == "test":
        ok, why = prereg_committed(root)
        if not ok:
            raise PreregMissing(f"refusing to generate the test split: {why}")
    th = Thresholds.from_profile(load_profile(profile_path))
    items = limited(plan(split), limit)
    jobs = jobs or default_jobs()
    start = time.perf_counter()
    args = [(item, split, th, str(root)) for item in items]
    if jobs == 1:
        rows = [_generate_one(a) for a in args]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            rows = list(pool.map(_generate_one, args, chunksize=1))
    path = manifest_path(root, split, limit)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    sheet_path = None
    make_sheet = (limit is None) if sheet is None else sheet
    if make_sheet:
        from printready.bench.sheet import write_contact_sheet

        sheet_path = root / "results" / "bench" / split / "contact-sheet.png"
        write_contact_sheet(rows, root, sheet_path)
    elapsed = time.perf_counter() - start
    summary = {
        "split": split,
        "samples": len(rows),
        "families": dict(Counter(r["family"] for r in rows)),
        "resamples": sum(r["resamples"] for r in rows),
        "seconds": elapsed,
        "manifest": str(path),
        "contact_sheet": str(sheet_path) if sheet_path else None,
    }
    log(f"bench generate --split {split}: {len(rows)} samples in {elapsed:.1f} s ({jobs} workers)")
    for family, n in summary["families"].items():
        log(f"  {family:<11} {n}")
    log(f"  resamples   {summary['resamples']}")
    log(f"  manifest    {path}")
    if sheet_path:
        log(f"  sheet       {sheet_path}")
    return summary


def read_manifest(path: Path | str) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
