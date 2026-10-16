"""End to end on a small run: `printready bench generate --limit 1` writes one sample per family.
Checks determinism, label completeness, the 10 % rule and that the stored ground truth matches
the pixels on disk."""

import hashlib

import numpy as np
import pytest
from PIL import Image

from printready.bench.bases import make_base, render
from printready.bench.defects import edge_runs
from printready.bench.generate import FAMILY_COUNTS, SEEDS, build, plan
from printready.bench.labels import Thresholds, near_threshold
from printready.profile import load_profile
from printready.types import (
    DETERMINISTIC_CHECK_IDS,
    FIXERS,
    OUTCOMES,
    STATUSES,
    SUBJECT_ALPHA,
    VISION_CHECK_IDS,
)


@pytest.fixture(scope="module")
def run(generated):
    root, _, rows = generated
    return root, rows


@pytest.fixture(scope="module")
def th():
    return Thresholds.from_profile(load_profile())


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _items(ids):
    by_id = {i.id: i for i in plan("dev")}
    return [by_id[i] for i in ids]


def test_one_sample_per_family_and_files_match_hashes(run):
    root, rows = run
    assert [r["family"] for r in rows] == list(FAMILY_COUNTS)
    for row in rows:
        assert _sha(root / row["image"]) == row["sha256"]
        if row["mask"]:
            assert _sha(root / row["mask"]) == row["mask_sha256"]
        else:
            assert row["mask_sha256"] is None
    assert not (root / "results" / "bench" / "dev" / "contact-sheet.png").exists()  # not for --limit


def test_rerun_is_byte_identical(run, th):
    _, rows = run
    by_id = {r["id"]: r for r in rows}
    for item in _items(["clean-000", "background-000", "text-000"]):
        built = build(item, SEEDS["dev"], th)
        assert hashlib.sha256(built.png).hexdigest() == by_id[item.id]["sha256"]
        if built.mask_png:
            assert hashlib.sha256(built.mask_png).hexdigest() == by_id[item.id]["mask_sha256"]


def test_every_row_has_complete_labels(run):
    _, rows = run
    for row in rows:
        checks = list(DETERMINISTIC_CHECK_IDS) + (list(VISION_CHECK_IDS) if row["family"] == "text" else [])
        assert list(row["expected"]) == checks
        for label in row["expected"].values():
            assert label["status"] in STATUSES and label["fixer"] in FIXERS
            if label["status"] in ("pass", "skip"):
                assert label["fixer"] == "none"
        assert row["outcome"] in OUTCOMES
        assert ("outcome_vision" in row) == (row["family"] == "text")
        assert row["spec"] == {"product": "die_cut", "size_in": 3.0}


def test_ten_percent_rule_holds(run, th):
    _, rows = run
    for row in rows:
        assert near_threshold(row["gt"], th) == [], row["id"]


def test_ground_truth_matches_pixels(run):
    """Alpha families: GT subject = alpha >= SUBJECT_ALPHA, and the stored bbox and edge runs are
    measured on it. Opaque families: the saved mask is the base's own alpha >= SUBJECT_ALPHA."""
    root, rows = run
    for row in rows:
        rgba = np.asarray(Image.open(root / row["image"]))
        assert rgba.shape == (row["height"], row["width"], 4)
        if row["mask"]:
            assert np.all(rgba[..., 3] == 255)
            mask = np.asarray(Image.open(root / row["mask"])) > 0
            base = make_base(SEEDS["dev"], row["bases"][0])
            assert np.array_equal(mask, render(base).rgba[..., 3] >= SUBJECT_ALPHA)
        else:
            mask = rgba[..., 3] >= SUBJECT_ALPHA
        rows_any, cols_any = np.flatnonzero(mask.any(1)), np.flatnonzero(mask.any(0))
        bbox = [cols_any[0], rows_any[0], cols_any[-1] + 1, rows_any[-1] + 1]
        assert bbox == row["gt"]["bbox_px"]
        assert edge_runs(mask) == row["gt"]["edge_runs_px"]


def _boundary(mask):
    p = np.pad(mask, 1)
    interior = p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
    return mask & ~interior


def test_islands_gap_is_the_true_shortest_distance(th):
    """The closed-form gap equals the shortest distance between the two parts' GT pixels."""
    built = build(_items(["islands-016"])[0], SEEDS["dev"], th)
    a, b = (_boundary(m) for m in built.planted.parts)  # nearest pixels always lie on the boundary
    gap = built.gt["gap_px"]
    ya, xa = np.nonzero(a)
    yb, xb = np.nonzero(b)
    near_a = xa >= xa.max() - gap - 4  # only pixels that can be near the facing sides
    near_b = xb <= xb.min() + gap + 4
    pa = np.stack([xa[near_a], ya[near_a]], 1).astype(float)
    pb = np.stack([xb[near_b], yb[near_b]], 1).astype(float)
    shortest = min(np.sqrt(((pa[k:k + 512, None] - pb[None]) ** 2).sum(-1)).min()
                   for k in range(0, len(pa), 512))
    assert gap <= shortest <= gap + 2.0
    assert built.gt["gap_in"] == pytest.approx(0.27, abs=1e-9)


def test_soft_alpha_ramp_is_exactly_w_px(run):
    root, rows = run
    row = next(r for r in rows if r["family"] == "soft_alpha")
    w = row["param"]["ramp_px"]
    alpha = np.asarray(Image.open(root / row["image"]))[..., 3]

    def box(m):
        ys, xs = np.nonzero(m)
        return np.array([xs.min(), ys.min(), xs.max(), ys.max()])

    # alpha > 0 reaches w * (1 - 0.5/255) out; alpha >= 240 only w * 15.5/255: 0.937 w apart.
    spread = np.abs(box(alpha > 0) - box(alpha >= 240))
    assert np.all(np.abs(spread - w * (1 - 16 / 255)) <= 1.5)
