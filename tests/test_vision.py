import base64
import io
import json

import numpy as np
import pytest
from PIL import Image

from printready import llm, spend
from printready.profile import load_profile
from printready.spend import BudgetExceeded
from printready.types import Artwork, Spec
from printready.vision import REMINDER, check_text, parse_answer

P = load_profile()


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv(spend.LEDGER_ENV, str(tmp_path / "ledger.jsonl"))
    monkeypatch.delenv(spend.CAP_ENV, raising=False)


def art(ppi=300.0, with_subject=True):
    """400 x 300 canvas; the subject box is rows 50..250 (200 px tall), all columns."""
    rgba = np.zeros((300, 400, 4), np.uint8)
    rgba[50:250, :, :3] = 200
    rgba[50:250, :, 3] = 255
    subject = rgba[..., 3] >= 128 if with_subject else None
    if not with_subject:
        rgba[..., 3] = 255
    return Artwork(rgba=rgba, subject=subject, ppi=ppi)


def client_for(tmp_path, *texts, price=None):
    script = tmp_path / "vision.json"
    responses = [t if isinstance(t, dict) else {"text": t} for t in texts]
    script.write_text(json.dumps({"responses": responses, "price": price} if price else responses), encoding="utf-8")
    return llm.make_client(f"fake:{script}", sleep=lambda s: None)


def answer(*items, notes="ok"):
    return json.dumps({"text": list(items), "notes": notes})


def item(seen, garbled=False, frac=0.1, intended=None):
    return {"seen": seen, "intended": intended or seen, "garbled": garbled, "cap_height_frac": frac}


SPEC = Spec("die_cut", 3.0)


def test_no_text_gives_two_passes(tmp_path):
    c = client_for(tmp_path, answer(notes="no text"))
    garbled, small = check_text(art(), SPEC, P, c)
    assert (garbled.check, garbled.status) == ("text_garbled", "pass")
    assert (small.check, small.status) == ("text_small", "pass")
    assert garbled.measured["model"] == "fake" and garbled.measured["request_sha256"]


def test_garbled_text_fails_for_a_person(tmp_path):
    c = client_for(tmp_path, answer(item("STIKCER", True, 0.2, "STICKER"), item("CLUB")))
    garbled, small = check_text(art(), SPEC, P, c)
    assert garbled.status == "fail" and garbled.fixer == "person"
    assert "STIKCER" in garbled.message and "STICKER" in garbled.message
    assert small.status == "pass"


def test_cap_height_frac_is_converted_to_points_with_art_ppi(tmp_path):
    # crop is 200 px tall at 300 PPI: cap_pt = frac * 200 / 300 * 72 = frac * 48
    c = client_for(tmp_path, answer(item("BIG", frac=0.2), item("tiny", frac=0.08)))
    _, small = check_text(art(), SPEC, P, c)
    m = small.measured
    assert m["min_cap_height_pt"] == pytest.approx(3.84)
    assert m["threshold_cap_pt"] == pytest.approx(P.cap_height_ratio * P.min_text_pt)
    assert small.status == "warn" and small.fixer == "customer"  # a bigger sticker fixes it
    # needed size: 2b + (3 - 2b) * 4.2 / 3.84
    assert m["min_size_in_for_text"] == pytest.approx(0.2 + 2.8 * 4.2 / 3.84, abs=0.01)
    assert "tiny" in small.message and "3.3 in" in small.message


def test_small_text_goes_to_a_person_when_a_bigger_size_would_be_soft(tmp_path):
    c = client_for(tmp_path, answer(item("tiny", frac=0.02)))
    _, small = check_text(art(ppi=100.0), SPEC, P, c)
    assert small.status == "warn" and small.fixer == "person"
    assert small.measured["min_size_in_for_text"] > small.measured["max_size_in_at_floor"]


def test_image_is_the_subject_box_and_scale_is_stated(tmp_path):
    c = client_for(tmp_path, answer())
    check_text(art(), Spec("die_cut", 3.0, prompt="a sticker that says CLUB"), P, c)
    system, user = c.transport.requests[0]["body"]["messages"]
    assert system["role"] == "system" and "JSON" in system["content"]
    text, image = user["content"]
    assert "3 in die-cut" in text["text"] and "1.33 in wide" in text["text"] and "CLUB" in text["text"]
    raw = base64.b64decode(image["image_url"]["url"].split(",", 1)[1])
    assert Image.open(io.BytesIO(raw)).size == (400, 200)  # cropped to the subject, not the canvas


def test_opaque_art_sends_the_whole_canvas(tmp_path):
    c = client_for(tmp_path, answer())
    check_text(art(with_subject=False), SPEC, P, c)
    url = c.transport.requests[0]["body"]["messages"][1]["content"][1]["image_url"]["url"]
    assert Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size == (400, 300)


def test_bad_json_gets_one_reminder_then_parses(tmp_path):
    c = client_for(tmp_path, "Sure! The text says CLUB.", "```json\n" + answer(item("CLUB")) + "\n```")
    garbled, _ = check_text(art(), SPEC, P, c)
    assert garbled.status == "pass" and "CLUB" in garbled.message
    retry = c.transport.requests[1]["body"]["messages"]
    assert retry[-2] == {"role": "assistant", "content": "Sure! The text says CLUB."}
    assert retry[-1] == {"role": "user", "content": REMINDER}


def test_bad_json_twice_is_a_skip_with_the_reason(tmp_path):
    c = client_for(tmp_path, "no idea", '{"text": [{"seen": "A"}]}')
    findings = check_text(art(), SPEC, P, c)
    assert [f.status for f in findings] == ["skip", "skip"]
    assert findings[0].measured["reason"] == "unreadable answer"
    assert "garbled" in findings[0].measured["error"]
    assert len(c.transport.requests) == 2  # exactly one retry


def test_api_error_is_a_skip_with_the_error(tmp_path):
    c = client_for(tmp_path, {"status": 400, "body": "image too large"})
    findings = check_text(art(), SPEC, P, c)
    assert [(f.check, f.status) for f in findings] == [("text_garbled", "skip"), ("text_small", "skip")]
    assert findings[0].measured["reason"] == "api error" and "image too large" in findings[0].measured["error"]


def test_budget_exceeded_propagates(tmp_path):
    spend.record("xai", "grok-4.3", 0, 0, 0, 0, 10.0, "earlier")
    c = client_for(tmp_path, answer(), price={"in_per_m": 1.25, "out_per_m": 2.5})
    with pytest.raises(BudgetExceeded):
        check_text(art(), SPEC, P, c)
    assert c.transport.requests == []


@pytest.mark.parametrize("text, problem", [
    ("", "no JSON object"),
    ("{nope}", "invalid JSON"),
    ('{"words": []}', '"text" list'),
    ('{"text": [{"seen": "A", "garbled": "yes"}]}', "garbled"),
    ('{"text": [{"seen": "A", "garbled": false, "cap_height_frac": 3}]}', "cap_height_frac"),
])
def test_parse_answer_rejects(text, problem):
    data, why = parse_answer(text)
    assert data is None and problem in why


def test_parse_answer_accepts_missing_height():
    data, why = parse_answer('Here: {"text": [{"seen": "A", "garbled": false}], "notes": ""} done')
    assert why == "" and data["text"][0]["seen"] == "A"
