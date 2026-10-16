"""Damage guard: every fix call records one Step; damaging fixes are reverted."""

import json

import cv2
import numpy as np

from printready.fixes._common import copy_with
from printready.guard import apply_fix
from printready.imageio import artwork_from_rgba
from printready.profile import load_profile
from printready.types import FixResult, Report, Spec, outcome

P = load_profile()
SPEC = Spec("die_cut", 1.0)


def badge_on_white():
    """A navy disc with a red centre on white."""
    rgba = np.full((300, 300, 4), 255, np.uint8)
    cv2.circle(rgba, (150, 150), 100, (40, 60, 160, 255), -1)
    cv2.circle(rgba, (150, 150), 40, (220, 30, 30, 255), -1)
    return artwork_from_rgba(rgba, SPEC, P)


def test_applied_fix_records_guard_numbers():
    art = badge_on_white()
    res = apply_fix("remove_background", art, SPEC, P)
    assert res.ok
    step = res.art.history[-1]
    assert (step.fix, step.ok, step.damaged) == ("remove_background", True, False)
    assert step.guard["metric"] == "damage_frac" and step.guard["value"] <= step.guard["limit"] == 0.02
    assert step.measured["bg_hex"] == "#ffffff"
    json.dumps(step.to_dict())
    border = apply_fix("add_border", res.art, SPEC, P)
    g = border.art.history[-1].guard
    assert (g["metric"], g["value"], g["limit"], g["passed"]) == ("subject_px_changed", 0, 0, True)
    assert len(border.art.history) == 2


def test_refused_fix_records_a_step_and_keeps_art():
    art = badge_on_white()
    res = apply_fix("add_border", art, SPEC, P)  # no subject yet
    assert not res.ok and not res.damaged
    assert res.art.subject is None and np.array_equal(res.art.rgba, art.rgba)
    assert [(s.fix, s.ok, s.damaged) for s in res.art.history] == [("add_border", False, False)]


def test_damaging_background_removal_is_reverted():
    art = badge_on_white()

    def remove_background(art, spec, profile):  # also erases the red centre: real subject colour
        good = apply_fix("remove_background", art, spec, profile).art
        rgba = good.rgba.copy()
        hole = np.zeros(rgba.shape[:2], np.uint8)
        cv2.circle(hole, (150, 150), 40, 1, -1)
        rgba[hole.astype(bool)] = 0
        subject = good.subject & ~hole.astype(bool)
        return FixResult(copy_with(good, rgba=rgba, subject=subject, history=[]), ok=True, note="Removed the background.")

    res = apply_fix(remove_background, art, SPEC, P)
    assert res.damaged and not res.ok
    step = res.art.history[-1]
    assert step.damaged and not step.ok and "Reverted" in step.note
    assert step.guard["value"] > step.guard["limit"]
    assert res.art.subject is None and np.array_equal(res.art.rgba, art.rgba)  # reverted
    assert outcome(res.art, Report([])) == "needs_person"


def test_border_fix_that_touches_subject_is_reverted():
    art = apply_fix("remove_background", badge_on_white(), SPEC, P).art

    def add_border(art, spec, profile, border_in=None):
        rgba = art.rgba.copy()
        rgba[150, 150] = (0, 0, 0, 255)  # one subject pixel changed
        return FixResult(copy_with(art, rgba=rgba), ok=True, note="Added a border.")

    res = apply_fix(add_border, art, SPEC, P)
    assert res.damaged
    assert res.art.history[-1].guard == {
        "metric": "subject_px_changed", "label": "subject pixels changed", "value": 1, "limit": 0, "passed": False,
    }
