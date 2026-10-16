"""The committed dev manifest against the family table in 03-EVAL section 1. Reads JSON only (no
images), so it is fast; skipped until `printready bench generate --split dev` has been run."""

from collections import Counter
from pathlib import Path

import pytest

from printready.bench.generate import FAMILY_COUNTS, read_manifest
from printready.bench.labels import Thresholds, near_threshold
from printready.profile import load_profile
from printready.types import DETERMINISTIC_CHECK_IDS

MANIFEST = Path(__file__).resolve().parents[2] / "data" / "bench" / "manifest-dev.jsonl"


@pytest.fixture(scope="module")
def rows():
    if not MANIFEST.exists():
        pytest.skip("data/bench/manifest-dev.jsonl not generated yet")
    return read_manifest(MANIFEST)


def test_family_counts(rows):
    assert Counter(r["family"] for r in rows) == FAMILY_COUNTS
    assert len({r["id"] for r in rows}) == 258


def test_ten_percent_rule(rows):
    th = Thresholds.from_profile(load_profile())
    assert {r["id"]: near_threshold(r["gt"], th) for r in rows if near_threshold(r["gt"], th)} == {}


def _table(row):
    """Non-pass statuses the 03-EVAL table plants, written out literally (not via labels.py)."""
    p, f = row["param"], row["family"]
    if f == "resolution":
        ppi = p["ppi"]
        if ppi < 150:
            return {"resolution": ("fail", "customer")}
        return {"resolution": ("warn", "customer") if ppi < 300 else None}
    if f == "background":
        fixer = "auto" if p["background"] in ("white", "saturated", "near_white_noise") else "person"
        return {"background": ("fail", fixer), "soft_alpha": ("skip", "none"),
                "edge_crop": ("skip", "none"), "islands": ("skip", "none")}
    if f == "islands":
        g = p["gap_in"]
        return {"islands": None if g < 0.2 else ("fail", "auto") if g <= 0.5 else ("fail", "person")}
    if f == "soft_alpha":
        return {"soft_alpha": None if p["ramp_in"] < 0.03 else ("warn", "person")}
    if f == "edge_crop":
        return {"edge_crop": ("warn", "auto") if p["case"] == "a" else ("fail", "person")}
    if f == "text":
        return {"text_garbled": ("fail", "person") if p["variant"] == "garbled" else None,
                "text_small": ("warn", "customer") if p.get("cap_pt", 99) < 4.2 else None}
    return {}


def test_labels_follow_the_family_table(rows):
    for row in rows:
        planted = {k: v for k, v in _table(row).items() if v is not None}
        for check, label in row["expected"].items():
            want = planted.get(check, ("pass", "none"))
            assert (label["status"], label["fixer"]) == want, (row["id"], check)
        assert set(DETERMINISTIC_CHECK_IDS) <= set(row["expected"])


def test_outcomes_follow_the_labels(rows):
    want = {
        "clean": {"ready"},
        "resolution": {"ready", "fixable"},
        "islands": {"ready", "fixable", "needs_person"},
        "soft_alpha": {"ready", "needs_person"},
        "edge_crop": {"fixable", "needs_person"},
        "background": {"fixable"},  # solid: removed; gradient/texture: whole-image sticker (fit_shape)
        "text": {"ready"},
    }
    for row in rows:
        assert row["outcome"] in want[row["family"]], row["id"]
        if row["family"] == "text":
            v = row["param"]["variant"]
            small = row["param"].get("cap_pt", 99) < 4.2
            expected = "needs_person" if v == "garbled" else "fixable" if small else "ready"
            assert row["outcome_vision"] == expected, row["id"]
    for row in rows:
        if row["family"] == "background" and row["param"]["background"] in ("gradient", "texture"):
            assert row["fixes"] == ["fit_shape"], row["id"]
            assert row["expected_final"] == {"file": "pass", "resolution": "pass", "background": "pass",
                                             "soft_alpha": "pass", "edge_crop": "pass", "islands": "pass",
                                             "product_fit": "warn"}, row["id"]
