"""Benchmark plan, word lists, font metrics and base art: fast checks that render little or nothing."""

from collections import Counter

import numpy as np
import pytest
from skimage import measure

from printready.bench import text as txt
from printready.bench.bases import (
    BASE_LONG_PX,
    MARGIN_FRAC,
    N_BASES,
    badge_indices,
    make_base,
    render,
    scaled_placement,
)
from printready.bench.generate import FAMILY_COUNTS, PreregMissing, generate_split, plan
from printready.types import SUBJECT_ALPHA

PRINTABLE_IN = 3.0 - 2 * 0.1


@pytest.mark.parametrize("split", ["dev", "test"])
def test_plan_matches_the_family_table(split):
    items = plan(split)
    assert len(items) == 258
    assert len({i.id for i in items}) == len(items)
    assert Counter(i.family for i in items) == FAMILY_COUNTS

    def per(family, key):
        return Counter(i.param[key] for i in items if i.family == family)

    assert per("resolution", "ppi") == {100: 7, 125: 7, 180: 7, 240: 7, 350: 7, 420: 7}
    assert per("background", "background") == {
        "white": 8, "saturated": 8, "near_white_noise": 8, "gradient": 8, "texture": 8}
    assert per("islands", "gap_in") == {0.10: 8, 0.15: 8, 0.27: 8, 0.40: 8, 0.80: 8}
    assert per("soft_alpha", "ramp_in") == {0.01: 8, 0.06: 8, 0.12: 8}
    assert per("edge_crop", "case") == {"a": 8, "b": 8, "c": 8}
    assert per("text", "variant") == {"correct": 16, "garbled": 16, "sized": 16}
    sized = Counter(i.param["cap_pt"] for i in items if i.family == "text" and i.param["variant"] == "sized")
    assert sized == {2.5: 4, 3.0: 4, 8.0: 4, 12.0: 4}
    assert all(len(set(i.bases)) == 2 for i in items if i.family == "islands")
    assert all(i.bases[0] in badge_indices() for i in items if i.family == "text")


def test_garbles_are_deliberate_misspellings():
    words = set(txt.WORDS)
    for garbled, intended, method in txt.GARBLES:
        assert intended in words and garbled not in words and garbled != intended
        if method == "swap":
            assert len(garbled) == len(intended) and sorted(garbled) == sorted(intended)
            diff = [k for k, (a, b) in enumerate(zip(garbled, intended)) if a != b]
            assert len(diff) == 2 and diff[1] == diff[0] + 1
        elif method == "double":
            assert len(garbled) == len(intended) + 1
            assert any(garbled[:k] + garbled[k + 1:] == intended and garbled[k] == garbled[k - 1]
                       for k in range(1, len(garbled)))
        else:
            assert method == "drop" and len(garbled) == len(intended) - 1
            assert any(intended[:k] + intended[k + 1:] == garbled for k in range(len(intended)))


@pytest.mark.parametrize("cap_px", [11.9, 14.3, 38.1, 57.2, 92.0])
def test_cap_height_from_font_metrics(cap_px):
    size = txt.font_size_for_cap(cap_px)
    _, top, _, bottom = txt.font(size).getbbox("H", anchor="ls")
    assert abs((bottom - top) - cap_px) <= 1.0
    assert txt.cap_ratio() == pytest.approx(1493 / 2048)


@pytest.mark.parametrize("seed", [7, 8])
def test_bases_meet_margin_and_ppi_by_geometry(seed):
    for i in range(N_BASES):
        base = make_base(seed, i)
        pl = base.placement
        x0, y0, x1, y1 = base.bbox_px()
        assert min(x0, pl.width - x1) >= MARGIN_FRAC * pl.width
        assert min(y0, pl.height - y1) >= MARGIN_FRAC * pl.height
        assert max(pl.width, pl.height) == 1200
        long_px = max(x1 - x0, y1 - y0)
        assert BASE_LONG_PX[0] - 1e-6 <= long_px <= BASE_LONG_PX[1] + 1e-6
        assert long_px / PRINTABLE_IN >= 330


def _near(mask: np.ndarray, radius: int = 2) -> np.ndarray:
    """Pixels within `radius` (Chebyshev) of a True pixel."""
    padded = np.pad(mask, radius)
    h, w = mask.shape
    out = np.zeros_like(mask)
    for dy in range(2 * radius + 1):
        for dx in range(2 * radius + 1):
            out |= padded[dy:dy + h, dx:dx + w]
    return out


def test_dev_bases_render_clean():
    """One component, no holes, anti-aliased edge at most 2 px (rendered small to stay fast)."""
    for i in range(N_BASES):
        base = make_base(7, i)
        alpha = render(base, scaled_placement(base, 300.0)).rgba[..., 3]
        mask = alpha >= SUBJECT_ALPHA
        assert measure.label(mask, connectivity=1, return_num=True)[1] == 1, f"base {i} is not one piece"
        assert measure.label(~mask, connectivity=1, return_num=True)[1] == 1, f"base {i} has a hole"
        partial = (alpha > 0) & (alpha < 255)
        assert np.all(_near(alpha == 255)[partial]) and np.all(_near(alpha == 0)[partial]), f"base {i}"


def test_test_split_refuses_without_committed_prereg(tmp_path):
    with pytest.raises(PreregMissing, match="does not exist"):
        generate_split("test", tmp_path, limit=1, jobs=1)
    (tmp_path / "PREREG.md").write_text("draft\n", encoding="utf-8")
    with pytest.raises(PreregMissing, match="not committed|could not run git"):
        generate_split("test", tmp_path, limit=1, jobs=1)
    assert not (tmp_path / "data").exists()
