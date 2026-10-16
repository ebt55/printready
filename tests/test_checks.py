"""Deterministic checks on small hand-built arrays (200-450 px)."""

import cv2
import numpy as np
import pytest

from printready.checks import load_failure_report, run_checks
from printready.checks.alpha import check_soft_alpha
from printready.checks.background import check_background
from printready.checks.edges import check_edge_crop
from printready.checks.file import check_file
from printready.checks.islands import check_islands
from printready.checks.resolution import check_resolution
from printready.geometry import components, cut_mask, long_side_px
from printready.imageio import artwork_from_rgba
from printready.profile import load_profile
from printready.types import DETERMINISTIC_CHECK_IDS, SUBJECT_ALPHA, Spec, outcome

P = load_profile()
SS = 4  # supersampling for anti-aliased discs
rng = np.random.default_rng(0)


def discs(h, w, circles, colour=(200, 60, 40)):
    """RGBA canvas with anti-aliased filled discs [(cx, cy, r), ...] on transparency."""
    big = np.zeros((h * SS, w * SS), np.uint8)
    for cx, cy, r in circles:
        cv2.circle(big, (round(cx * SS), round(cy * SS)), round(r * SS), 255, -1)
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., :3] = colour
    rgba[..., 3] = cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)
    return rgba


def at_ppi(rgba, ppi):
    """Artwork plus the Spec whose size makes the subject print at `ppi`."""
    long_px = long_side_px(rgba[..., 3] >= SUBJECT_ALPHA) or max(rgba.shape[:2])
    spec = Spec("die_cut", long_px / ppi + 2 * P.border_in)
    return artwork_from_rgba(rgba, spec, P), spec


def flatten(rgba, background):
    a = rgba[..., 3:4] / 255.0
    out = np.empty_like(rgba)
    out[..., :3] = (rgba[..., :3] * a + background * (1 - a)).round().astype(np.uint8)
    out[..., 3] = 255
    return out


BADGE = discs(300, 300, [(150, 150, 100)])


# ---------------------------------------------------------------- run_checks

def test_run_checks_order_and_clean_art_is_ready():
    art, spec = at_ppi(BADGE, 400)
    report = run_checks(art, spec, P)
    assert tuple(f.check for f in report.findings) == DETERMINISTIC_CHECK_IDS
    assert report.status() == "pass"
    assert outcome(art, report) == "ready"


def test_opaque_art_skips_mask_checks():
    art, spec = at_ppi(flatten(BADGE, np.array([255, 255, 255])), 400)
    assert art.subject is None
    report = run_checks(art, spec, P)
    for check in ("soft_alpha", "edge_crop", "islands"):
        f = report.by_check(check)
        assert f.status == "skip" and f.measured["reason"] == "needs background removal first"
    assert report.by_check("resolution").measured["basis"] == "canvas"


def test_load_failure_report():
    report = load_failure_report("x.png could not be decoded")
    f = report.by_check("file")
    assert (f.status, f.fixer) == ("fail", "none")
    assert [x.status for x in report.findings[1:]] == ["skip"] * 5
    assert outcome(None, report) == "needs_person"


# ---------------------------------------------------------------- file

def test_file_pass_and_fails():
    art, spec = at_ppi(BADGE, 400)
    assert check_file(art, spec, P).status == "pass"
    art.meta["bytes"] = 20_000_001
    f = check_file(art, spec, P)
    assert (f.status, f.fixer) == ("fail", "customer")
    small, spec = at_ppi(discs(50, 50, [(25, 25, 20)]), 400)
    assert (check_file(small, spec, P).status, check_file(small, spec, P).fixer) == ("fail", "none")
    empty = artwork_from_rgba(np.zeros((100, 100, 4), np.uint8), Spec("die_cut", 1), P)
    assert check_file(empty, Spec("die_cut", 1), P).status == "fail"


# ---------------------------------------------------------------- resolution

@pytest.mark.parametrize(
    "ppi, status, fixer", [(400, "pass", "none"), (200, "warn", "customer"), (120, "fail", "customer")]
)
def test_resolution_bands(ppi, status, fixer):
    art, spec = at_ppi(BADGE, ppi)
    f = check_resolution(art, spec, P)
    assert (f.status, f.fixer) == (status, fixer)
    long_px = 200  # disc diameter, as measured by the subject bbox
    assert f.measured["ppi"] == pytest.approx(ppi, rel=0.01)
    assert f.measured["max_size_in_at_target"] == pytest.approx(long_px / 300 + 0.2, rel=0.01)
    assert f.measured["max_size_in_at_floor"] == pytest.approx(long_px / 150 + 0.2, rel=0.01)
    assert f.measured["one_pt_px"] == pytest.approx(ppi / 72, rel=0.01)


def test_resolution_person_when_even_one_inch_is_soft():
    art, spec = at_ppi(discs(100, 100, [(50, 50, 40)]), 60)  # 80 px: at 150 PPI only 0.73 in
    f = check_resolution(art, spec, P)
    assert (f.status, f.fixer) == ("fail", "person")


# ---------------------------------------------------------------- background

def test_background_real_alpha_passes():
    art, spec = at_ppi(BADGE, 400)
    assert check_background(art, spec, P).status == "pass"


@pytest.mark.parametrize("name", ["white", "saturated", "near_white_noise"])
def test_background_solid_is_auto(name):
    bg = {
        "white": np.full((300, 300, 3), 255.0),
        "saturated": np.full((300, 300, 3), (20.0, 160.0, 60.0)),
        "near_white_noise": np.clip(250 + rng.normal(0, 1.5, (300, 300, 3)), 0, 255),
    }[name]
    art, spec = at_ppi(flatten(BADGE, bg), 400)
    f = check_background(art, spec, P)
    assert (f.status, f.fixer) == ("fail", "auto")
    assert f.measured["ring_uniform_frac"] >= P.bg_ring_uniform_frac
    if name == "white":
        assert f.measured["colour_hex"] == "#ffffff"


@pytest.mark.parametrize("name", ["gradient", "texture"])
def test_background_non_uniform_is_person(name):
    if name == "gradient":
        bg = np.repeat(np.linspace(0, 255, 300)[None, :, None], 300, axis=0).repeat(3, axis=2)
    else:
        bg = rng.uniform(0, 255, (300, 300, 3))
    art, spec = at_ppi(flatten(BADGE, bg), 400)
    f = check_background(art, spec, P)
    assert (f.status, f.fixer) == ("fail", "person")
    assert f.measured["ring_uniform_frac"] < 0.6


# ---------------------------------------------------------------- soft_alpha

def ramp_disc(ramp_px, radius=100, size=320):
    yy, xx = np.indices((size, size))
    r = np.hypot(xx - size / 2, yy - size / 2)
    rgba = np.zeros((size, size, 4), np.uint8)
    rgba[..., :3] = (30, 30, 30)
    rgba[..., 3] = np.clip(255 * (1 - (r - radius) / ramp_px), 0, 255).astype(np.uint8)
    return rgba


def test_soft_alpha_thin_edge_passes():
    art, spec = at_ppi(ramp_disc(4), 400)  # 0.01 in ramp
    f = check_soft_alpha(art, spec, P)
    assert f.status == "pass" and f.measured["band_p95_in"] < 0.012


def test_soft_alpha_wide_band_warns_person():
    art, spec = at_ppi(ramp_disc(24), 400)  # 0.06 in ramp
    f = check_soft_alpha(art, spec, P)
    assert (f.status, f.fixer) == ("warn", "person")
    assert 0.045 < f.measured["band_p95_in"] < 0.06
    assert f.boxes


# ---------------------------------------------------------------- edge_crop

def rect_art(x0, x1, y0, y1, h=300, w=300):
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[y0:y1, x0:x1] = (10, 120, 200, 255)
    return rgba


def test_edge_crop_pass_warn_fail():
    art, spec = at_ppi(rect_art(100, 200, 50, 200), 400)
    assert check_edge_crop(art, spec, P).status == "pass"

    art, spec = at_ppi(rect_art(140, 160, 0, 150), 400)  # touches the top for 20 px = 0.05 in
    f = check_edge_crop(art, spec, P)
    assert (f.status, f.fixer) == ("warn", "auto")
    assert f.boxes == [(140, 0, 160, 1)]

    art, spec = at_ppi(rect_art(100, 200, 0, 150), 400)  # 100 px = 0.25 in along the top
    f = check_edge_crop(art, spec, P)
    assert (f.status, f.fixer) == ("fail", "person")
    assert f.measured["edge"] == "top" and f.measured["longest_run_in"] == pytest.approx(0.25)


def test_edge_crop_warns_when_built_cut_runs_off_canvas():
    art, spec = at_ppi(rect_art(10, 200, 50, 200), 400)  # 10 px margin, border is 40 px
    art.cut = cut_mask(art.subject, art.ppi, P.border_in)
    art.border_in = P.border_in
    f = check_edge_crop(art, spec, P)
    assert (f.status, f.fixer, f.measured["cut_on_edge"]) == ("warn", "auto", True)


# ---------------------------------------------------------------- islands

PPI = 200


def two_discs(gap_in, radius=50):
    gap = gap_in * PPI
    w = round(40 + 4 * radius + gap + 40)
    left = 40 + radius
    rgba = discs(180, w, [(left, 90, radius), (left + 2 * radius + gap, 90, radius)])
    return at_ppi(rgba, PPI)


@pytest.mark.parametrize(
    "gap_in, status, fixer",
    [(0.15, "pass", "none"), (0.30, "fail", "auto"), (0.40, "fail", "auto"), (0.80, "fail", "person")],
)
def test_islands_by_gap(gap_in, status, fixer):
    art, spec = two_discs(gap_in)
    f = check_islands(art, spec, P)
    assert (f.status, f.fixer) == (status, fixer)
    if status == "fail":
        assert f.measured["components"] == 2 and len(f.boxes) == 2


def test_islands_is_dilate_only_no_closing():
    # 0.22 in gap: a 0.1 in border on each side leaves 0.02 in open. The add_border closing
    # (diameter min_neck_in) would join it, but the islands check must not apply it.
    art, spec = two_discs(0.22)
    assert len(components(cut_mask(art.subject, art.ppi, P.border_in, close_in=P.min_neck_in), 1).masks) == 1
    f = check_islands(art, spec, P)
    assert (f.status, f.fixer, f.measured["basis"]) == ("fail", "auto", "dilate")


def test_islands_specks_are_dropped_and_counted():
    rgba = discs(300, 300, [(120, 150, 90)])
    rgba[10:13, 280:283] = (0, 0, 0, 255)  # 9 px dot; a speck is < 0.0004 in2 = 16 px at 200 PPI
    art, spec = at_ppi(rgba, PPI)
    f = check_islands(art, spec, P)
    assert f.status == "pass" and f.measured["specks"] == 1 and f.measured["speck_px"] == 9


def test_islands_uses_built_cut():
    art, spec = two_discs(0.30)
    art.border_in = 0.25
    art.cut = cut_mask(art.subject, art.ppi, art.border_in)
    f = check_islands(art, spec, P)
    assert (f.status, f.measured["basis"], f.measured["border_in"]) == ("pass", "cut", 0.25)
