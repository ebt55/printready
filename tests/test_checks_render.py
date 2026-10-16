import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest

from printready.checks import run_checks
from printready.cutline import cutline_svg
from printready.geometry import cut_mask
from printready.imageio import load_artwork
from printready.profile import load_profile
from printready.render import render_overlay, render_proof
from printready.types import Finding, Report, Spec

P = load_profile()
FIXTURES = Path(__file__).parent / "fixtures"
SVG = "{http://www.w3.org/2000/svg}"


def badge(size_in=1.0):
    spec = Spec("die_cut", size_in)
    return load_artwork(FIXTURES / "badge.png", spec, P), spec


def path_points(d):
    nums = [float(t) for t in d.replace("M", " ").replace("L", " ").replace("Z", " ").split()]
    return np.array(nums).reshape(-1, 2)


def test_cutline_requires_cut():
    art, spec = badge()
    with pytest.raises(ValueError, match="art.cut is None"):
        cutline_svg(art, spec, P)


def test_cutline_svg_in_inches_matches_order_size():
    art, spec = badge(1.0)  # 280 px subject -> 350 PPI; 360 px canvas leaves room for the border
    art.cut = cut_mask(art.subject, art.ppi, P.border_in, P.min_neck_in, P.speck_max_in2)
    root = ET.fromstring(cutline_svg(art, spec, P))
    w_in = 360 / art.ppi
    assert root.get("viewBox") == f"0 0 {w_in:.4f} {w_in:.4f}" and root.get("width") == f"{w_in:.4f}in"
    paths = root.findall(f"{SVG}path")
    assert len(paths) == 1
    assert paths[0].get("stroke") == "#ff00ff" and float(paths[0].get("stroke-width")) == pytest.approx(0.5 / 72, abs=1e-5)
    pts = path_points(paths[0].get("d"))
    assert pts.min() >= 0 and pts.max() <= w_in
    long_in = (pts.max(axis=0) - pts.min(axis=0)).max()
    assert long_in == pytest.approx(spec.size_in, rel=0.02)  # subject + 2 x border = ordered size


def test_cutline_one_path_per_piece():
    art, spec = badge(1.0)
    cut = np.zeros_like(art.subject)
    cut[20:100, 20:100] = True
    cut[200:300, 200:300] = True
    art.cut = cut
    assert len(ET.fromstring(cutline_svg(art, spec, P)).findall(f"{SVG}path")) == 2


def test_render_proof_preview_does_not_mutate():
    art, spec = badge(1.0)
    before = art.rgba.copy()
    img = render_proof(art, spec, P)
    assert art.cut is None and np.array_equal(art.rgba, before)
    px = np.array(img)
    pad = int(np.ceil(P.border_in * art.ppi)) + 4
    assert img.width == 360 + 2 * pad and img.height > 360 + 2 * pad  # padded preview + label strip
    magenta = (px[..., 0] == 255) & (px[..., 1] == 0) & (px[..., 2] == 255)
    assert magenta.sum() > 500


def test_render_overlay_marks_flagged_boxes():
    art, spec = badge(3.0)
    flagged = render_overlay(art, run_checks(art, spec, P))  # resolution fails at 3 in, no boxes
    assert flagged.width == 360 and flagged.height > 360  # banner strip added
    report = Report([Finding("islands", "fail", "two pieces", {}, "auto", boxes=[(10, 10, 60, 60)])])
    img = np.array(render_overlay(art, report))
    assert img.shape[0] > 360
    red = (img[..., 0] > 200) & (img[..., 1] < 60) & (img[..., 2] < 60)
    assert red.sum() > 100
    assert render_overlay(art, Report([])).size == (360, 360)
