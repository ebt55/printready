import json

import numpy as np
import pytest

from printready.types import (
    CHECK_IDS,
    CORRECTIVE_FIXES,
    DETERMINISTIC_CHECK_IDS,
    SUBJECT_ALPHA,
    VISION_CHECK_IDS,
    Artwork,
    Finding,
    FixResult,
    Report,
    RunResult,
    Spec,
    Step,
    outcome,
)


def f(check: str, status: str, fixer: str = "auto", **measured) -> Finding:
    return Finding(check=check, status=status, message=f"{check} {status}", measured=measured, fixer=fixer)


def art_with(*steps: Step) -> Artwork:
    return Artwork(rgba=np.zeros((4, 4, 4), np.uint8), subject=None, ppi=300.0, history=list(steps))


def test_constants():
    assert SUBJECT_ALPHA == 128
    assert DETERMINISTIC_CHECK_IDS == ("file", "resolution", "background", "soft_alpha", "edge_crop", "islands")
    assert VISION_CHECK_IDS == ("text_garbled", "text_small")
    assert CHECK_IDS == DETERMINISTIC_CHECK_IDS + VISION_CHECK_IDS
    assert "add_border" not in CORRECTIVE_FIXES


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


CLEAN = Report([f("file", "pass"), f("resolution", "pass"), f("islands", "pass", "person")])


def test_outcome_ready():
    # add_border is not corrective, and a pass with fixer person does not count.
    assert outcome(art_with(Step("add_border", True, False, "")), CLEAN) == "ready"
    # A corrective fix that failed (ok=False) changed nothing.
    assert outcome(art_with(Step("pad_canvas", False, False, "")), CLEAN) == "ready"


def test_outcome_fixable():
    assert outcome(art_with(Step("remove_background", True, False, "")), CLEAN) == "fixable"
    customer = Report([f("file", "pass"), f("resolution", "warn", "customer")])
    assert outcome(art_with(), customer) == "fixable"


@pytest.mark.parametrize("fixer", ["person", "none"])
def test_outcome_needs_person_from_findings(fixer):
    report = Report([f("background", "pass"), f("soft_alpha", "warn", fixer)])
    assert outcome(art_with(), report) == "needs_person"


def test_outcome_needs_person_from_handoff_damage_and_skip():
    assert outcome(art_with(), CLEAN, handoff=True) == "needs_person"
    assert outcome(art_with(Step("remove_background", False, True, "reverted")), CLEAN) == "needs_person"
    assert outcome(art_with(), Report([f("file", "pass"), f("text_garbled", "skip", "none")])) == "needs_person"
    assert outcome(None, Report([f("file", "fail", "none")])) == "needs_person"


def test_finding_rejects_unknown_values():
    with pytest.raises(ValueError):
        f("internal_cut", "fail")
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


def test_artwork_and_results_to_dict_exclude_arrays():
    subject = np.zeros((4, 6), bool)
    subject[1:3, 1:3] = True
    step = Step("remove_background", True, False, "white removed")
    art = Artwork(
        rgba=np.zeros((4, 6, 4), np.uint8), subject=subject, ppi=412.5, offset=(2, 3),
        history=[step], meta={"path": "a.png", "bytes": 1234, "format": "PNG"},
    )
    data = FixResult(art=art, ok=True, note="ok").to_dict()
    json.dumps(data)
    assert data["damaged"] is False
    assert data["art"] == {
        "width": 6, "height": 4, "ppi": 412.5, "offset": [2, 3], "subject_px": 4, "border_in": None,
        "cut_px": None, "history": [step.to_dict()], "meta": {"path": "a.png", "bytes": 1234, "format": "PNG"},
    }
    assert Step.from_dict(step.to_dict()) == step
    run = RunResult(
        mode="rules", art=art, before=CLEAN, after=CLEAN, outcome="fixable", customer_message="Approve?",
        outputs={"proof": "out/a/proof.png"},
    )
    rd = json.loads(json.dumps(run.to_dict()))
    assert rd["mode"] == "rules" and rd["person_notes"] == [] and rd["after"]["status"] == "pass"


def test_artwork_validates_and_copy_is_deep():
    with pytest.raises(ValueError):
        Artwork(rgba=np.zeros((4, 6, 3), np.uint8), subject=None, ppi=300)
    with pytest.raises(ValueError):
        Artwork(rgba=np.zeros((4, 6, 4), np.uint8), subject=np.zeros((4, 5), bool), ppi=300)
    with pytest.raises(ValueError):
        Artwork(rgba=np.zeros((4, 6, 4), np.uint8), subject=None, ppi=0)
    art = art_with()
    clone = art.copy()
    clone.rgba[0, 0, 0] = 9
    clone.history.append(Step("pad_canvas", True, False, ""))
    assert art.rgba[0, 0, 0] == 0 and art.history == []
