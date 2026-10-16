import json

import numpy as np
import pytest

from printready.types import (
    CHECK_IDS,
    DETERMINISTIC_CHECK_IDS,
    VISION_CHECK_IDS,
    Artwork,
    Finding,
    FixResult,
    Report,
    Spec,
    decide,
)


def f(check: str, status: str, fixer: str = "auto", **measured) -> Finding:
    return Finding(check=check, status=status, message=f"{check} {status}", measured=measured, fixer=fixer)


def test_check_ids_split():
    assert DETERMINISTIC_CHECK_IDS == (
        "file", "resolution", "background", "soft_alpha", "edge_crop", "islands", "internal_cut",
    )
    assert VISION_CHECK_IDS == ("text_garbled", "text_small")
    assert CHECK_IDS == DETERMINISTIC_CHECK_IDS + VISION_CHECK_IDS


def test_status_worst_wins():
    assert Report([f("file", "pass"), f("resolution", "warn")]).status() == "warn"
    assert Report([f("file", "warn"), f("islands", "fail"), f("background", "pass")]).status() == "fail"
    assert Report([f("file", "pass"), f("resolution", "pass")]).status() == "pass"


def test_status_ignores_skip():
    assert Report([f("file", "pass"), f("islands", "skip")]).status() == "pass"
    assert Report([f("islands", "skip"), f("resolution", "warn")]).status() == "warn"
    assert Report([f("islands", "skip")]).status() == "skip"
    assert Report([]).status() == "skip"


def test_by_check():
    report = Report([f("file", "pass"), f("islands", "fail")])
    assert report.by_check("islands").status == "fail"
    assert report.by_check("edge_crop") is None


def test_decide_ready():
    # A pass with fixer "person" does not count: only warn/fail findings decide.
    report = Report([f("file", "pass", "person"), f("islands", "skip", "none"), f("resolution", "pass")])
    assert decide(report) == "ready"


def test_decide_fixable():
    report = Report([f("background", "fail", "auto"), f("resolution", "warn", "customer"), f("file", "pass")])
    assert decide(report) == "fixable"


@pytest.mark.parametrize("fixer", ["person", "none"])
def test_decide_needs_person(fixer):
    report = Report([f("background", "fail", "auto"), f("soft_alpha", "warn", fixer)])
    assert decide(report) == "needs_person"


def test_finding_rejects_unknown_values():
    with pytest.raises(ValueError):
        f("neck", "fail")
    with pytest.raises(ValueError):
        f("file", "error")
    with pytest.raises(ValueError):
        f("file", "fail", "robot")


def test_spec_validation():
    assert Spec("die_cut", 3.0).prompt is None
    with pytest.raises(ValueError):
        Spec("die_cut", 0)
    with pytest.raises(ValueError):
        Spec("kiss_cut", 3.0)


def test_report_to_dict_is_json_and_round_trips():
    finding = Finding(
        check="resolution", status="warn", message="Soft at 3 in.",
        measured={"ppi": np.float64(212.5), "one_pt_px": np.int64(3)}, fixer="customer",
        boxes=[(np.int32(1), 2, 3, 4)],
    )
    data = Report([finding]).to_dict()
    text = json.dumps(data)
    assert data["status"] == "warn"
    assert Report.from_dict(json.loads(text)).findings[0] == finding


def test_artwork_to_dict_excludes_arrays():
    rgba = np.zeros((4, 6, 4), np.uint8)
    subject = np.zeros((4, 6), bool)
    subject[1:3, 1:3] = True
    art = Artwork(rgba=rgba, subject=subject, history=["removed background"])
    data = FixResult(art=art, ok=True, note="ok").to_dict()
    json.dumps(data)
    assert data["art"] == {
        "width": 6, "height": 4, "subject_px": 4, "border_in": None, "cut_px": None,
        "history": ["removed background"],
    }


def test_artwork_validates_shapes_and_copy_is_deep():
    with pytest.raises(ValueError):
        Artwork(rgba=np.zeros((4, 6, 3), np.uint8))
    with pytest.raises(ValueError):
        Artwork(rgba=np.zeros((4, 6, 4), np.uint8), subject=np.zeros((4, 5), bool))
    art = Artwork(rgba=np.zeros((2, 2, 4), np.uint8))
    clone = art.copy()
    clone.rgba[0, 0, 0] = 9
    clone.history.append("x")
    assert art.rgba[0, 0, 0] == 0 and art.history == []
