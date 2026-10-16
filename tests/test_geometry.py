import math

import numpy as np
import pytest

from printready import geometry as g
from printready.profile import load_profile
from printready.types import Spec

P = load_profile()


def disc_mask(h, w, cx, cy, r):
    yy, xx = np.indices((h, w))
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r


def test_bbox_long_side_and_margin():
    m = np.zeros((50, 80), bool)
    m[10:20, 5:45] = True
    assert g.bbox(m) == (5, 10, 45, 20)
    assert g.long_side_px(m) == 40
    assert g.min_margin_px(m) == 5
    assert g.bbox(np.zeros((5, 5), bool)) is None


def test_ppi_for_long_side():
    assert g.ppi_for_long_side(840, Spec("die_cut", 3.0), P) == pytest.approx(300)
    with pytest.raises(ValueError):
        g.ppi_for_long_side(840, Spec("die_cut", 0.2), P)


def test_dilate_is_a_euclidean_disc():
    m = np.zeros((101, 101), bool)
    m[50, 50] = True
    d = g.dilate(m, 20)
    assert abs(d.sum() - math.pi * 400) < 2 * math.pi * 20
    assert d[50, 70] and not d[50, 71] and not d[64, 65]  # (14, 15) is 20.5 px away


def test_erode_close_and_fill_holes():
    m = np.zeros((60, 100), bool)
    m[20:40, 10:45] = True
    m[20:40, 49:90] = True  # 4 px gap
    assert len(g.components(m, 1).masks) == 2
    closed = g.close(m, 3)
    assert len(g.components(closed, 1).masks) == 1
    assert (closed | m).sum() == closed.sum()  # closing never removes pixels
    assert g.erode(m, 2).sum() < m.sum()
    ring = disc_mask(60, 60, 30, 30, 20) & ~disc_mask(60, 60, 30, 30, 10)
    assert g.fill_holes(ring)[30, 30] and not ring[30, 30]


def test_components_speck_filter_uses_area_of():
    m = np.zeros((100, 100), bool)
    m[10:50, 10:50] = True
    m[80:82, 80:82] = True  # 4 px speck
    found = g.components(m, 10)
    assert len(found.masks) == 1 and found.specks == 1 and found.speck_px == 4
    # Judged by subject area inside a dilated component, not by the dilated area.
    dilated = g.dilate(m, 5)
    found = g.components(dilated, 10, area_of=m)
    assert len(found.masks) == 1 and found.specks == 1


def test_cut_mask_contains_subject_and_border():
    ppi = 200
    subject = disc_mask(200, 200, 100, 100, 50)
    cut = g.cut_mask(subject, ppi, 0.1, close_in=0.125, speck_in2=0.0004)
    assert (cut | subject).sum() == cut.sum()
    assert cut[100, 100 + 50 + 18] and not cut[100, 100 + 50 + 24]  # border ~20 px
    assert len(g.components(cut, 1).masks) == 1
    speckled = subject.copy()
    speckled[5, 5] = True
    assert not g.cut_mask(speckled, ppi, 0.1, speck_in2=0.0004)[5, 5]


def test_soft_alpha_p95_on_linear_ramp():
    h = w = 300
    yy, xx = np.indices((h, w))
    r = np.hypot(xx - 150, yy - 150)
    ramp_w = 40
    alpha = np.clip(255 * (1 - (r - 60) / ramp_w), 0, 255).astype(np.uint8)
    p95 = g.soft_alpha_p95_px(alpha)
    assert 0.8 * ramp_w <= p95 <= 0.97 * ramp_w
    assert g.soft_alpha_p95_px(np.full((10, 10), 255, np.uint8)) == 0.0
    assert math.isinf(g.soft_alpha_p95_px(np.full((10, 10), 100, np.uint8)))


def test_longest_edge_run():
    m = np.zeros((60, 80), bool)
    m[0, 10:30] = True
    m[5:50, 0] = True
    run = g.longest_edge_run(m)
    assert (run.edge, run.length_px, run.start, run.end) == ("left", 45, 5, 50)
    assert run.box(m.shape) == (0, 5, 1, 50)
    assert g.longest_edge_run(np.zeros((5, 5), bool)).length_px == 0
    assert g.edge_pixel_count(m) == 65


def test_ring_uniformity():
    img = np.full((200, 200, 3), 255, np.uint8)
    img[60:140, 60:140] = (20, 30, 200)
    ring = g.ring_uniformity(img, 8.0)
    assert ring.uniform_frac == 1.0 and ring.rgb == (255, 255, 255) and ring.band_px == 4
    gradient = np.repeat(np.linspace(0, 255, 200).astype(np.uint8)[None, :, None], 200, axis=0).repeat(3, axis=2)
    assert g.ring_uniformity(gradient, 8.0).uniform_frac < 0.6


def test_outline_polygons():
    polys = g.outline_polygons(disc_mask(100, 120, 60, 50, 30), 300)
    assert len(polys) == 1
    xs, ys = polys[0][:, 0], polys[0][:, 1]
    assert 29 <= xs.min() <= 31 and 89 <= xs.max() <= 91 and 19 <= ys.min() <= 21
