"""`printready bench run`: run the real detectors and the rules pipeline over a benchmark split.

Only the public API is used: `imageio.load_artwork` + `checks.run_checks` on the image as given
(BEFORE), and `pipeline.run_rules` for the whole rules pipeline (AFTER: final report, steps with
their damage-guard numbers, outcome). The pipeline's per-image outputs go to the gitignored
`results/bench/<split>/scratch/`. One line per sample goes to `predictions.jsonl` (no images).

A detector that raises is recorded as an error for that sample, never retried or dropped.
"""

from __future__ import annotations

import hashlib
import json
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

from printready.bench.generate import default_jobs, read_manifest, rounded_json
from printready.profile import load_profile
from printready.types import SUBJECT_ALPHA, Report, Spec

IOU_BAND_PX = 2  # IoU is computed outside this band around the true subject edge


class BenchDataError(RuntimeError):
    """The split's images are missing or do not match the manifest."""


def results_dir(root: Path, split: str, limit: int | None = None) -> Path:
    base = Path(root) / "results" / "bench" / split
    return base / f"limit{limit}" if limit is not None else base


def default_manifest(root: Path, split: str) -> Path:
    return Path(root) / "data" / "bench" / f"manifest-{split}.jsonl"


def limit_rows(rows: list[dict[str, Any]], limit: int | None) -> list[dict[str, Any]]:
    """The first `limit` rows of each family, in manifest order."""
    if limit is None:
        return rows
    seen: dict[str, int] = {}
    out = []
    for row in rows:
        if seen.get(row["family"], 0) < limit:
            seen[row["family"]] = seen.get(row["family"], 0) + 1
            out.append(row)
    return out


# --- ground truth vs prediction -------------------------------------------------------------------


def _dilate_square(mask: np.ndarray, r: int) -> np.ndarray:
    """Dilation by a (2r+1)^2 square (separable: rows, then columns)."""
    h, w = mask.shape
    p = np.pad(mask, ((0, 0), (r, r)))
    rows = np.zeros_like(mask)
    for k in range(2 * r + 1):
        rows |= p[:, k:k + w]
    p = np.pad(rows, ((r, r), (0, 0)))
    out = np.zeros_like(mask)
    for k in range(2 * r + 1):
        out |= p[k:k + h, :]
    return out


def place(gt: np.ndarray, shape: tuple[int, int], offset: tuple[int, int]) -> np.ndarray:
    """The ground-truth mask moved into the final canvas: original (x, y) is now (x+dx, y+dy)."""
    dx, dy = offset
    out = np.zeros(shape, dtype=bool)
    h, w = gt.shape
    ys, xs = slice(max(dy, 0), min(dy + h, shape[0])), slice(max(dx, 0), min(dx + w, shape[1]))
    out[ys, xs] = gt[ys.start - dy:ys.stop - dy, xs.start - dx:xs.stop - dx]
    return out


def band_iou(pred: np.ndarray, gt: np.ndarray, band_px: int = IOU_BAND_PX) -> float:
    """IoU of two masks on one canvas, ignoring pixels within `band_px` of the true edge."""
    band = _dilate_square(gt, band_px) & _dilate_square(~gt, band_px)  # near both sides of the edge
    keep = ~band
    union = int(((pred | gt) & keep).sum())
    return float(((pred & gt) & keep).sum()) / union if union else 1.0


def ground_truth(root: Path, row: dict[str, Any]) -> np.ndarray:
    """The sample's true subject: the saved mask for opaque samples, else alpha >= SUBJECT_ALPHA."""
    if row.get("mask"):
        return np.asarray(Image.open(Path(root) / row["mask"])) > 0
    return np.asarray(Image.open(Path(root) / row["image"]).convert("RGBA"))[..., 3] >= SUBJECT_ALPHA


def _findings(report: Report, measured: bool) -> dict[str, dict[str, Any]]:
    out = {}
    for f in report.findings:
        entry: dict[str, Any] = {"status": f.status, "fixer": f.fixer}
        if measured:
            entry["measured"] = f.to_dict()["measured"]
        out[f.check] = entry
    return out


def _error(stage: str, exc: BaseException) -> str:
    where = traceback.extract_tb(exc.__traceback__)[-1] if exc.__traceback__ else None
    loc = f" at {Path(where.filename).name}:{where.lineno}" if where else ""
    return f"{stage}: {type(exc).__name__}: {exc}{loc}"


def predict(row: dict[str, Any], root: Path, scratch: Path, profile_path: Path | None = None) -> dict[str, Any]:
    """BEFORE checks, the AFTER pipeline and the ground-truth comparison for one sample."""
    from printready.checks import run_checks  # the detectors, used only through their public API
    from printready.imageio import load_artwork
    from printready.pipeline import run_rules

    profile = load_profile(profile_path)
    spec = Spec(row["spec"]["product"], float(row["spec"]["size_in"]))
    path = Path(root) / row["image"]
    rec: dict[str, Any] = {"id": row["id"], "family": row["family"], "errors": []}
    start = time.perf_counter()
    try:
        art = load_artwork(path, spec, profile)
        rec["before"] = _findings(run_checks(art, spec, profile), measured=True)
    except Exception as exc:  # a crash is a result, not a reason to stop the benchmark
        rec["before"] = None
        rec["errors"].append(_error("run_checks", exc))
    try:
        run = run_rules(path, spec, profile, scratch / row["id"], client=None)
    except Exception as exc:
        run = None
        rec["errors"].append(_error("run_rules", exc))
    if run is not None:
        pipeline_before = {f.check: f.status for f in run.before.findings}
        rec["pipeline_before_agrees"] = rec["before"] is not None and pipeline_before == {
            c: v["status"] for c, v in rec["before"].items()}
        rec["after"] = _findings(run.after, measured=False)
        rec["outcome"] = run.outcome
        rec["handoff_reason"] = run.handoff_reason
        art = run.art
        rec["steps"] = [] if art is None else [
            {"fix": s.fix, "ok": s.ok, "damaged": s.damaged, "guard": s.to_dict()["guard"], "note": s.note}
            for s in art.history]
        rec["offset"] = None if art is None else list(art.offset)
        rec["iou"] = None
        if art is not None and art.subject is not None:
            try:
                gt = place(ground_truth(root, row), art.subject.shape, art.offset)
                rec["iou"] = band_iou(art.subject, gt)
            except Exception as exc:
                rec["errors"].append(_error("iou", exc))
    else:
        rec.update(after=None, outcome=None, handoff_reason=None, steps=[], offset=None, iou=None)
    rec["elapsed_s"] = time.perf_counter() - start
    return rounded_json(rec)


def _predict_one(args: tuple[dict[str, Any], str, str, str | None]) -> dict[str, Any]:
    row, root, scratch, profile_path = args
    return predict(row, Path(root), Path(scratch), Path(profile_path) if profile_path else None)


def check_images(root: Path, rows: list[dict[str, Any]]) -> None:
    """Every image (and mask) exists and matches the manifest's sha256."""
    for row in rows:
        for key, sha_key in (("image", "sha256"), ("mask", "mask_sha256")):
            if not row.get(key):
                continue
            path = Path(root) / row[key]
            if not path.exists():
                raise BenchDataError(f"{path} is missing; run `printready bench generate` first")
            if hashlib.sha256(path.read_bytes()).hexdigest() != row[sha_key]:
                raise BenchDataError(f"{path} does not match the manifest; regenerate the split")


def run_split(
    split: str,
    root: Path | str = ".",
    *,
    limit: int | None = None,
    jobs: int | None = None,
    manifest: Path | None = None,
    profile_path: Path | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Predict every manifest row of a split; write predictions.jsonl and run.json."""
    root = Path(root)
    manifest = Path(manifest) if manifest else default_manifest(root, split)
    if not manifest.exists():
        raise BenchDataError(f"{manifest} not found; run `printready bench generate --split {split}` first")
    rows = limit_rows(read_manifest(manifest), limit)
    check_images(root, rows)
    out = results_dir(root, split, limit)
    scratch = root / "results" / "bench" / split / "scratch"
    jobs = jobs or default_jobs()
    start = time.perf_counter()
    args = [(row, str(root), str(scratch), str(profile_path) if profile_path else None) for row in rows]
    if jobs == 1:
        preds = [_predict_one(a) for a in args]
    else:
        with ProcessPoolExecutor(max_workers=jobs) as pool:
            preds = list(pool.map(_predict_one, args, chunksize=1))
    elapsed = time.perf_counter() - start
    out.mkdir(parents=True, exist_ok=True)
    with (out / "predictions.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for pred in preds:
            fh.write(json.dumps(pred, ensure_ascii=False) + "\n")
    info = {
        "split": split,
        "samples": len(preds),
        "jobs": jobs,
        "seconds": round(elapsed, 1),
        "manifest": manifest.name,
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "errors": sum(1 for p in preds if p["errors"]),
    }
    (out / "run.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    log(f"bench run --split {split}: {len(preds)} samples in {elapsed:.1f} s ({jobs} workers), "
        f"{info['errors']} with errors")
    log(f"  predictions {out / 'predictions.jsonl'}")
    return info
