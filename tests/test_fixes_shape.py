"""fit_shape: a scene becomes a whole-image rounded-rectangle sticker without touching a pixel."""

import xml.etree.ElementTree as ET

import numpy as np
import pytest

from printready.checks import run_checks
from printready.cutline import cutline_svg
from printready.fixes import fit_shape, recommend_size
from printready.guard import apply_fix
from printready.imageio import artwork_from_rgba
from printready.profile import load_profile
from printready.render import render_proof
from printready.types import Spec

P = load_profile()
SPEC = Spec("die_cut", 3.0)


def scene(h=300, w=400, seed=1):
    """An opaque photo-like image: a smooth gradient plus noise, no flat background."""
    rng = np.random.default_rng(seed)
    yy, xx = np.indices((h, w))
    rgba = np.empty((h, w, 4), np.uint8)
    rgba[..., 0] = (xx * 255 // w).astype(np.uint8)
    rgba[..., 1] = (yy * 255 // h).astype(np.uint8)
    rgba[..., 2] = rng.integers(60, 120, (h, w), dtype=np.uint8)
    rgba[..., 3] = 255
    return artwork_from_rgba(rgba, SPEC, P)


def test_fit_shape_changes_the_product_not_the_pixels():
    art = scene()
    result = apply_fix("fit_shape", art, SPEC, P)
    assert result.ok, result.note
    new = result.art
    assert new.shape == "rounded_rect" and art.shape == "die_cut"
    assert np.array_equal(new.rgba, art.rgba)
    assert new.history[-1].guard == {
        "metric": "image_px_changed", "label": "image pixels changed", "value": 0, "limit": 0, "passed": True,
    }
    # the one sanctioned ppi change: canvas long side over the size plus the bleed on both sides
    assert new.ppi == pytest.approx(400 / (3.0 + 2 * P.bleed_in))
    inset, radius = round(P.bleed_in * new.ppi), round(P.shape_corner_radius_in * new.ppi)
    cut = new.cut
    assert cut[150, inset] and not cut[150, inset - 1] and cut[inset, 200] and not cut[inset - 1, 200]
    assert not cut[inset, inset] and cut[inset + radius, inset + radius]  # rounded corner
    assert result.measured["finished_w_in"] == pytest.approx(3.0, abs=0.01)


def test_fit_shape_refusals():
    rgba = np.zeros((200, 200, 4), np.uint8)
    rgba[50:150, 50:150] = 255  # real transparency: suits a die-cut
    art = artwork_from_rgba(rgba, SPEC, P)
    assert not fit_shape(art, SPEC, P).ok
    shaped = fit_shape(scene(), SPEC, P).art
    assert not fit_shape(shaped, SPEC, P).ok


def test_checks_on_a_rounded_rectangle():
    art = fit_shape(scene(), SPEC, P).art
    report = run_checks(art, SPEC, P)
    assert [f.check for f in report.findings][-1] == "product_fit"
    for check in ("background", "soft_alpha", "edge_crop", "islands"):
        f = report.by_check(check)
        assert (f.status, f.message, f.measured) == ("pass", "Not applicable to a whole-image sticker.", {"applies": False})
    fit = report.by_check("product_fit")
    assert (fit.status, fit.fixer) == ("warn", "customer") and "ask a person" in fit.message
    res = report.by_check("resolution")
    assert res.measured["basis"] == "image"
    assert res.measured["max_size_in_at_target"] == pytest.approx(400 / 300 - 2 * P.bleed_in, abs=0.001)
    assert recommend_size(art, SPEC, P)["max_size_in_at_floor"] == pytest.approx(400 / 150 - 2 * P.bleed_in, abs=0.001)


def test_fit_shape_changes_no_measurement_except_through_the_scale():
    art = scene()
    before = {f.check: f for f in run_checks(art, SPEC, P).findings}
    shaped = fit_shape(art, SPEC, P).art
    after = {f.check: f for f in run_checks(shaped, SPEC, P).findings}
    assert after["file"].measured == before["file"].measured
    scale = art.ppi / shaped.ppi  # every physical length grows by this factor
    assert scale == pytest.approx((3.0 + 2 * P.bleed_in) / (3.0 - 2 * P.border_in))
    assert after["resolution"].measured["one_pt_px"] == pytest.approx(before["resolution"].measured["one_pt_px"] / scale, abs=0.01)


def test_rounded_rect_cutline_and_proof():
    art = fit_shape(scene(), SPEC, P).art
    root = ET.fromstring(cutline_svg(art, SPEC, P))
    rect = root.find("{http://www.w3.org/2000/svg}rect")
    assert root.find("{http://www.w3.org/2000/svg}path") is None
    assert float(rect.get("x")) == P.bleed_in and float(rect.get("rx")) == P.shape_corner_radius_in
    assert float(rect.get("width")) == pytest.approx(3.0, abs=0.001)
    proof = np.array(render_proof(art, SPEC, P))
    assert proof.shape[1] == 400  # no padding: the whole image is the sticker
    magenta = (proof[..., 0] == 255) & (proof[..., 1] == 0) & (proof[..., 2] == 255)
    assert magenta.sum() > 500
    bleed = proof[2, 200].astype(int)  # trimmed bleed is shown faded towards white
    assert bleed.min() > art.rgba[2, 200, :3].astype(int).min()
