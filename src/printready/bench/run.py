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


# --- vision (live, text family only) ---------------------------------------------------------------

VISION_FAMILY = "text"
DEFAULT_VISION_MODEL = "xai:grok-4.3"
DEFAULT_VISION_MAX_USD = 0.15
RETRY_MARGIN = 1.2  # a parse failure costs one more call
FALLBACK_TOKENS = (2600, 400)  # in (2000 for the image + the prompt), out: when the ledger has no history


def _ledger_rows() -> list[dict[str, Any]]:
    from printready import spend

    path = spend.ledger_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def vision_estimate(model: str, n_calls: int) -> tuple[float, float, str]:
    """(total USD, USD per call, basis). Per call: the largest earlier vision call of this model in
    the spend ledger, priced with no cache credit; else a generous fixed token count. Times n and
    a 20 % margin for parse retries."""
    from printready import spend

    price = spend.price_for(model)
    name = model.split(":", 1)[-1]
    past = [r for r in _ledger_rows() if r.get("purpose") == "vision" and r.get("model") == name]
    if past:
        t_in, t_out = max(r["tokens_in"] for r in past), max(r["tokens_out"] for r in past)
        basis = f"largest of {len(past)} earlier vision call(s) in the ledger: {t_in} in, {t_out} out"
    else:
        t_in, t_out = FALLBACK_TOKENS
        basis = f"no vision calls in the ledger yet; assumed {t_in} tokens in, {t_out} out"
    per_call = spend.cost(price, tokens_in=t_in, tokens_out=t_out)
    return per_call * n_calls * RETRY_MARGIN, per_call, basis


def run_vision(
    split: str,
    root: Path | str = ".",
    *,
    model: str = DEFAULT_VISION_MODEL,
    yes: bool = False,
    resume: bool = False,
    max_usd: float = DEFAULT_VISION_MAX_USD,
    limit: int | None = None,
    manifest: Path | None = None,
    profile_path: Path | None = None,
    env_file: Path | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """vision.check_text on every text-family sample; writes vision.jsonl and vision-run.json.

    Prints the estimate first. Without `yes` nothing is spent. Refuses when the estimate is above
    `max_usd`, and stops early (remaining samples recorded as not run) if actual spend would pass it.
    Spend is this client's own `cost_usd` (the ledger is shared with other runs). With `resume`,
    samples that already have findings from the same model in vision.jsonl are kept, not re-called.
    """
    from printready import spend
    from printready.imageio import load_artwork
    from printready.llm import make_client
    from printready.vision import check_text

    root = Path(root)
    manifest = Path(manifest) if manifest else default_manifest(root, split)
    if not manifest.exists():
        raise BenchDataError(f"{manifest} not found; run `printready bench generate --split {split}` first")
    rows = limit_rows([r for r in read_manifest(manifest) if r["family"] == VISION_FAMILY], limit)
    check_images(root, rows)
    out = results_dir(root, split, limit)
    kept: dict[str, dict[str, Any]] = {}
    prior_cost = 0.0
    if resume and (out / "vision.jsonl").exists():
        for line in (out / "vision.jsonl").read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec.get("findings") and rec.get("model") == model:
                kept[rec["id"]] = rec
                prior_cost += rec.get("cost_usd") or 0.0
    todo = [r for r in rows if r["id"] not in kept]
    estimate_usd, per_call, basis = vision_estimate(model, len(todo))
    log(f"bench run --vision: {len(todo)} calls to {model} ({len(kept)} kept from an earlier run), "
        f"estimated ${estimate_usd:.4f} (${per_call:.5f} per call; {basis}; "
        f"+{RETRY_MARGIN - 1:.0%} for retries); budget ${max_usd:.2f} for this run")
    info: dict[str, Any] = {"split": split, "model": model, "samples": len(rows), "kept": len(kept),
                            "estimate_usd": estimate_usd, "estimate_basis": basis, "max_usd": max_usd, "ran": False}
    if estimate_usd > max_usd:
        log("  estimate is above the budget: nothing was called")
        return info
    if not yes:
        log("  dry run: re-run with --yes to make the calls")
        return info

    profile = load_profile(profile_path)
    client = make_client(model, env_file)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    start = time.perf_counter()
    stopped = None
    for row in rows:
        if row["id"] in kept:
            records.append(kept[row["id"]])
            continue
        rec: dict[str, Any] = {"id": row["id"], "family": row["family"], "model": model, "errors": []}
        spent = client.cost_usd
        if stopped or spent + per_call > max_usd:
            stopped = stopped or f"budget: ${spent:.4f} spent of ${max_usd:.2f}"
            rec.update(findings=None, cost_usd=0.0, elapsed_s=0.0)
            rec["errors"].append(f"not run ({stopped})")
            records.append(rounded_json(rec))
            continue
        t0, before = time.perf_counter(), client.cost_usd
        try:
            spec = Spec(row["spec"]["product"], float(row["spec"]["size_in"]))
            art = load_artwork(Path(root) / row["image"], spec, profile)
            findings = check_text(art, spec, profile, client)
            rec["findings"] = _findings(Report(findings), measured=True)
        except spend.BudgetExceeded as exc:
            rec["findings"] = None
            rec["errors"].append(_error("check_text", exc))
            stopped = "the spend cap refused the call"
        except Exception as exc:  # recorded, never retried
            rec["findings"] = None
            rec["errors"].append(_error("check_text", exc))
        rec["cost_usd"] = client.cost_usd - before
        rec["elapsed_s"] = time.perf_counter() - t0
        records.append(rounded_json(rec))
    with (out / "vision.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for rec in records:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    cost_usd = client.cost_usd
    info.update(ran=True, completed=sum(1 for r in records if r["findings"] is not None),
                cost_usd=round(prior_cost + cost_usd, 6), cost_usd_this_run=round(cost_usd, 6),
                seconds=round(time.perf_counter() - start, 1), stopped=stopped,
                manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest())
    (out / "vision-run.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    log(f"  {info['completed']}/{len(rows)} samples done in {info['seconds']} s, this run cost ${cost_usd:.4f}"
        + (f"; stopped early: {stopped}" if stopped else ""))
    log(f"  vision predictions {out / 'vision.jsonl'}")
    return info
