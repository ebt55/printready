"""A fix must never change the measured value of a check it does not address.

One fixture carries every property at once: a soft 0.06 in alpha ramp (soft_alpha warn), two parts
0.3 in apart (islands fail/auto), a stub touching the top edge for 0.07 in (edge_crop warn/auto),
and 200 PPI at the ordered size (resolution warn). Each fix is applied on its own and in pipeline
order; every check it does not target must report identical status and measurements.
"""

import cv2
import numpy as np
import pytest

from printready.checks import run_checks
from printready.guard import apply_fix
from printready.imageio import artwork_from_rgba
from printready.profile import load_profile
from printready.types import DETERMINISTIC_CHECK_IDS, Spec

P = load_profile()
PPI = 200
TARGETS = {
    "pad_canvas": {"edge_crop"},
    "add_border": {"islands", "edge_crop"},
    "bridge_islands": {"islands", "edge_crop"},
}


def fixture():
    h, w = 300, 560
    yy, xx = np.indices((h, w))
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., :3] = (200, 60, 40)
    ramp_px = 0.06 * PPI  # linear ramp from alpha 255 at r=60 to 0 at r=72
    alpha_a = np.clip(255 * (1 - (np.hypot(xx - 130, yy - 160) - 60) / ramp_px), 0, 255)
    big = np.zeros((h * 4, w * 4), np.uint8)
    cv2.circle(big, (322 * 4, 160 * 4), 66 * 4, 255, -1)  # part B, 0.3 in from part A's subject edge
    big[0:100 * 4, 315 * 4:329 * 4] = 255  # 14 px stub to the top edge = 0.07 in
    alpha_b = cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)
    rgba[..., 3] = np.maximum(alpha_a, alpha_b).astype(np.uint8)
    long_px = 388 - 64  # subject bbox width
    spec = Spec("die_cut", long_px / PPI + 2 * P.border_in)
    return artwork_from_rgba(rgba, spec, P), spec


def measured(report):
    return {f.check: (f.status, f.measured) for f in report.findings}


def test_fixture_has_every_property():
    art, spec = fixture()
    report = run_checks(art, spec, P)
    assert art.ppi == pytest.approx(PPI, rel=0.01)
    assert [(report.by_check(c).status, report.by_check(c).fixer) for c in ("resolution", "soft_alpha", "edge_crop", "islands")] == [
        ("warn", "customer"), ("warn", "person"), ("warn", "auto"), ("fail", "auto"),
    ]


@pytest.mark.parametrize("fix", list(TARGETS))
def test_each_fix_alone_leaves_other_checks_unchanged(fix):
    art, spec = fixture()
    before = measured(run_checks(art, spec, P))
    result = apply_fix(fix, art, spec, P)
    assert result.ok, result.note
    after = measured(run_checks(result.art, spec, P))
    for check in DETERMINISTIC_CHECK_IDS:
        if check not in TARGETS[fix]:
            assert after[check] == before[check], f"{fix} changed {check}"


def test_pipeline_order_leaves_other_checks_unchanged():
    art, spec = fixture()
    reference = measured(run_checks(art, spec, P))
    touched: set[str] = set()
    for fix in ("pad_canvas", "add_border", "bridge_islands"):
        result = apply_fix(fix, art, spec, P)
        assert result.ok, result.note
        art, touched = result.art, touched | TARGETS[fix]
        now = measured(run_checks(art, spec, P))
        for check in DETERMINISTIC_CHECK_IDS:
            if check not in touched:
                assert now[check] == reference[check], f"after {fix}: {check} changed"
    assert now["soft_alpha"][0] == "warn"  # the border hides nothing: the shadow still needs a person
    assert now["islands"][0] == "pass" and now["edge_crop"][0] == "pass"  # what the fixes did target
