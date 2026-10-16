"""Each fix: happy path and refusal, on small synthetic arrays."""

import cv2
import numpy as np
import pytest

from printready.fixes import add_border, bridge_islands, pad_canvas, recommend_size, remove_background
from printready.geometry import components, edge_pixel_count, long_side_px, min_margin_px
from printready.guard import subject_px_changed
from printready.imageio import artwork_from_rgba
from printready.profile import load_profile
from printready.types import SUBJECT_ALPHA, Spec

P = load_profile()
SS = 4
RED = (200, 60, 40)


def discs(h, w, circles, colour=RED):
    big = np.zeros((h * SS, w * SS), np.uint8)
    for cx, cy, r in circles:
        cv2.circle(big, (round(cx * SS), round(cy * SS)), round(r * SS), 255, -1)
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., :3] = colour
    rgba[..., 3] = cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)
    return rgba


def flatten(rgba, bg):
    a = rgba[..., 3:4] / 255.0
    out = np.empty_like(rgba)
    out[..., :3] = (rgba[..., :3] * a + np.asarray(bg, float) * (1 - a)).round().astype(np.uint8)
    out[..., 3] = 255
    return out


def at_ppi(rgba, ppi):
    long_px = long_side_px(rgba[..., 3] >= SUBJECT_ALPHA) or max(rgba.shape[:2])
    spec = Spec("die_cut", long_px / ppi + 2 * P.border_in)
    return artwork_from_rgba(rgba, spec, P), spec


DISC = discs(300, 300, [(150, 150, 100)])
TRUE_MASK = DISC[..., 3] >= SUBJECT_ALPHA


def opaque_disc(bg=(255, 255, 255)):
    rgba = flatten(DISC, bg)
    spec = Spec("die_cut", 200 / 400 + 0.2)  # 400 PPI once the 200 px disc is the subject
    return artwork_from_rgba(rgba, spec, P), spec


# ---------------------------------------------------------------- remove_background

@pytest.mark.parametrize("bg", [(255, 255, 255), (20, 160, 60)])
def test_remove_background_keeps_subject_and_feathers_edge(bg):
    art, spec = opaque_disc(bg)
    res = remove_background(art, spec, P)
    assert res.ok, res.note
    assert art.subject is None and art.history == []  # input untouched
    new = res.art
    iou = (new.subject & TRUE_MASK).sum() / (new.subject | TRUE_MASK).sum()
    assert iou > 0.98
    assert new.ppi == pytest.approx(400, rel=0.02)
    alpha = new.rgba[..., 3]
    assert alpha[0, 0] == 0 and alpha[150, 150] == 255
    partial = (alpha > 0) & (alpha < 255)
    assert 0 < partial.sum() < 2 * np.pi * 100 * 2  # a ~1 px ring
    # unblended: edge pixels carry the subject colour, not a background-coloured fringe
    assert np.abs(new.rgba[partial][:, :3].astype(int) - RED).mean() < 40
    assert res.measured["removed_frac"] == pytest.approx(1 - TRUE_MASK.mean(), abs=0.01)


def test_remove_background_drops_specks():
    rgba = flatten(discs(400, 400, [(150, 150, 100)]), (255, 255, 255))
    rgba[380:382, 380:382, :3] = 0  # dark 2x2 speck far from the disc
    spec = Spec("die_cut", 0.7)
    res = remove_background(artwork_from_rgba(rgba, spec, P), spec, P)
    assert res.ok and res.measured["specks_dropped"] == 1
    assert res.art.rgba[380, 380, 3] == 0


def test_remove_background_refusals():
    art, spec = opaque_disc()
    assert not remove_background(remove_background(art, spec, P).art, spec, P).ok  # already transparent

    gradient = np.repeat(np.linspace(0, 255, 300)[None, :, None], 300, axis=0).repeat(3, axis=2)
    res = remove_background(*opaque_disc_on(gradient))
    assert not res.ok and "not one colour" in res.note

    tiny = flatten(discs(300, 300, [(150, 150, 8)]), (255, 255, 255))  # would remove > 95 %
    res = remove_background(artwork_from_rgba(tiny, Spec("die_cut", 1), P), Spec("die_cut", 1), P)
    assert not res.ok and res.measured["removed_frac"] > 0.95


def opaque_disc_on(bg_image):
    rgba = flatten(DISC, bg_image)
    spec = Spec("die_cut", 1.0)
    return artwork_from_rgba(rgba, spec, P), spec, P


# ---------------------------------------------------------------- add_border

def test_add_border_builds_cut_and_never_touches_subject():
    art, spec = at_ppi(DISC, 400)
    res = add_border(art, spec, P)
    assert res.ok and art.cut is None
    new = res.art
    assert new.border_in == 0.1 and new.cut is not None
    assert subject_px_changed(art, new) == 0
    assert (new.cut | art.subject).sum() == new.cut.sum()
    assert len(components(new.cut, 1).masks) == 1
    ring = new.cut & (art.rgba[..., 3] == 0)
    assert ring.any() and (new.rgba[ring] == 255).all()  # border pixels are opaque white
    assert (new.rgba[~new.cut] == art.rgba[~new.cut]).all()  # nothing outside the cut changes


def test_add_border_refusals():
    art, spec = opaque_disc()
    assert not add_border(art, spec, P).ok  # no subject yet
    art, spec = at_ppi(DISC, 400)
    assert not add_border(art, spec, P, border_in=0.03).ok  # below border_min_in


# ---------------------------------------------------------------- bridge_islands

PPI = 200


def two_discs(gap_in, radius=50):
    gap = gap_in * PPI
    margin = 60
    w = round(2 * margin + 4 * radius + gap)
    left = margin + radius
    return at_ppi(discs(220, w, [(left, 110, radius), (left + 2 * radius + gap, 110, radius)]), PPI)


def test_bridge_islands_grows_border_until_one_piece():
    art, spec = two_discs(0.4)
    res = bridge_islands(art, spec, P)
    assert res.ok, res.note
    assert 0.1 < res.art.border_in <= P.max_bridge_border_in
    assert len(components(res.art.cut, 1).masks) == 1
    assert subject_px_changed(art, res.art) == 0


def test_bridge_islands_closing_alone_can_join():
    art, spec = two_discs(0.3)  # 0.1 in left open by the border; the 0.125 in closing joins it
    res = bridge_islands(art, spec, P)
    assert res.ok and res.art.border_in == pytest.approx(0.1)


def test_bridge_islands_refusals():
    art, spec = two_discs(0.8)
    res = bridge_islands(art, spec, P)
    assert not res.ok and "stay apart" in res.note
    art, spec = at_ppi(DISC, 400)
    assert not bridge_islands(art, spec, P).ok  # already one piece


# ---------------------------------------------------------------- pad_canvas

def rect(x0, x1, y0, y1, h=300, w=300):
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[y0:y1, x0:x1] = (10, 120, 200, 255)
    return rgba


def test_pad_canvas_adds_room_and_updates_offset():
    art, spec = at_ppi(rect(140, 160, 0, 150), 400)  # touches the top for 0.05 in
    res = pad_canvas(art, spec, P)
    assert res.ok, res.note
    new = res.art
    need = int(np.ceil(P.max_bridge_border_in * art.ppi)) + 2
    assert new.offset == (0, need) and min_margin_px(new.subject) >= need
    assert subject_px_changed(art, new) == 0
    border = add_border(new, spec, P).art
    assert edge_pixel_count(border.cut) == 0  # the border now fits


def test_pad_canvas_refusals():
    art, spec = at_ppi(rect(100, 200, 0, 150), 400)  # cut off along 0.25 in of the top edge
    res = pad_canvas(art, spec, P)
    assert not res.ok and "cut off" in res.note
    roomy = discs(400, 400, [(200, 200, 60)])
    art, spec = at_ppi(roomy, 400)
    assert not pad_canvas(art, spec, P).ok  # 140 px margin > 0.25 in at 400 PPI


def test_recommend_size():
    art, spec = at_ppi(DISC, 100)  # 200 px across
    rec = recommend_size(art, spec, P)
    assert rec["max_size_in_at_target"] == pytest.approx(200 / 300 + 0.2, abs=0.01)
    assert rec["max_size_in_at_floor"] == pytest.approx(200 / 150 + 0.2, abs=0.01)


# ---------------------------------------------------------------- scattered art (dev realset d07)

def starry(n_stars=400, seed=3):
    """A disc on a flat navy sky with many 1-2 px stars: the ring is one colour, the result is not."""
    rng = np.random.default_rng(seed)
    rgba = flatten(discs(400, 400, [(200, 200, 90)], colour=(240, 170, 60)), (20, 25, 60))
    yy, xx = np.indices((400, 400))
    outside = np.hypot(xx - 200, yy - 200) > 110
    ys, xs = np.nonzero(outside[12:-12, 12:-12])
    pick = rng.choice(len(ys), n_stars, replace=False)
    for y, x in zip(ys[pick] + 12, xs[pick] + 12):
        rgba[y:y + rng.integers(1, 3), x:x + rng.integers(1, 3), :3] = 250
    return rgba


def test_remove_background_refuses_scattered_specks():
    spec = Spec("die_cut", 3.0)
    res = remove_background(artwork_from_rgba(starry(), spec, P), spec, P)
    assert not res.ok and "not one flat colour" in res.note
    assert res.measured["specks"] > res.measured["max_specks"] == 250
    calm = remove_background(artwork_from_rgba(starry(n_stars=30), spec, P), spec, P)
    assert calm.ok and calm.measured["specks"] <= 250  # a few stars are just specks to drop


def test_scattered_pieces_are_refused():
    centres = [(60 + 140 * i, 60 + 140 * j, 22) for i in range(3) for j in range(3)]  # 9 parts, far apart
    rgba = discs(400, 400, centres)
    spec = Spec("die_cut", 3.0)
    res = remove_background(artwork_from_rgba(flatten(rgba, (255, 255, 255)), spec, P), spec, P)
    assert not res.ok and res.measured["pieces"] == 9 > res.measured["max_pieces"]
    art = artwork_from_rgba(rgba, spec, P)
    bridged = bridge_islands(art, spec, P)
    assert not bridged.ok and "too many" in bridged.note and bridged.measured["pieces"] == 9
