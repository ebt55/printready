import base64
import io
import json

import numpy as np
import pytest
from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

from printready import llm, spend, vision
from printready.profile import load_profile
from printready.spend import BudgetExceeded
from printready.types import Artwork, Spec
from printready.vision import REMINDER, cap_height_px, check_text, parse_answer

P = load_profile()
FONT = font_manager.findfont("DejaVu Sans:bold")
SPEC = Spec("die_cut", 3.0)


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv(spend.LEDGER_ENV, str(tmp_path / "ledger.jsonl"))
    monkeypatch.delenv(spend.CAP_ENV, raising=False)
    monkeypatch.setenv(vision.TEXT_SMALL_ENV, "1")  # off by default; these tests pin the measurement


def text_art(word="SHOP", cap_px=40, ppi=300.0, with_subject=True):
    """400 x 300 canvas; the subject is rows 50..250 (200 px tall), light grey, with `word` drawn in
    dark letters whose capitals are `cap_px` tall, top-left at (40, 120). Returns (art, text box px)."""
    font = ImageFont.truetype(FONT, size=100)
    top, bottom = font.getbbox("H")[1], font.getbbox("H")[3]
    font = ImageFont.truetype(FONT, size=max(4, round(100 * cap_px / (bottom - top))))
    img = Image.new("RGBA", (400, 300), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 50, 399, 249], fill=(200, 200, 200, 255))
    draw.text((40, 120), word, font=font, fill=(20, 20, 60, 255))
    rgba = np.array(img)
    box = font.getbbox(word)
    text_box = (40 + box[0], 120 + box[1], 40 + box[2], 120 + box[3])
    subject = rgba[..., 3] >= 128 if with_subject else None
    if not with_subject:
        rgba[..., 3] = 255
    return Artwork(rgba=rgba, subject=subject, ppi=ppi), text_box


def as_fraction(text_box, crop=(0, 50, 400, 250)):
    cx0, cy0, cx1, cy1 = crop
    x0, y0, x1, y1 = text_box
    w, h = cx1 - cx0, cy1 - cy0
    return [round((x0 - cx0) / w, 3), round((y0 - cy0) / h, 3), round((x1 - cx0) / w, 3), round((y1 - cy0) / h, 3)]


def client_for(tmp_path, *texts, price=None):
    script = tmp_path / "vision.json"
    responses = [t if isinstance(t, dict) else {"text": t} for t in texts]
    script.write_text(json.dumps({"responses": responses, "price": price} if price else responses), encoding="utf-8")
    return llm.make_client(f"fake:{script}", sleep=lambda s: None)


def answer(*items, notes="ok"):
    return json.dumps({"text": list(items), "notes": notes})


def item(seen, broken=False, box=None, intended=None):
    return {"seen": seen, "intended": intended or seen, "broken": broken, "box": box}


def on_white(art):
    return vision._on_white(art.rgba)


# ---------------------------------------------------------------- measurement

@pytest.mark.parametrize("cap_px", [12, 20, 40])
def test_cap_height_is_measured_from_pixels_even_with_a_loose_box(cap_px):
    art, (x0, y0, x1, y1) = text_art(cap_px=cap_px)
    h = y1 - y0
    loose = (x0 - 6, y0 - 0.2 * h, x1 + 9, y1 + 0.15 * h)  # a model's box is never exact
    assert cap_height_px(on_white(art), loose) == pytest.approx(cap_px, abs=max(1.5, 0.08 * cap_px))


def test_a_box_one_box_height_off_still_finds_the_line():
    # seen live on the dev bench: grok-4.3 put the box for 3 pt text entirely below the word
    art, (x0, y0, x1, y1) = text_art(cap_px=12)
    h = 3 * (y1 - y0)  # a loose box, three times the text height...
    below = (x0 - 10, y1 + 2, x1 + 10, y1 + 2 + h)  # ...that does not overlap the text at all
    assert cap_height_px(on_white(art), below) == pytest.approx(12, abs=1.5)


def test_mixed_case_uses_the_tall_letters():
    art, box = text_art(word="Bakery", cap_px=30)
    assert cap_height_px(on_white(art), box) == pytest.approx(30, abs=3)


def test_no_contrast_or_a_tiny_box_measures_nothing():
    art, _ = text_art()
    rgb = on_white(art)
    assert cap_height_px(rgb, (300, 60, 390, 100)) is None  # plain grey fill
    assert cap_height_px(rgb, (10, 10, 12, 12)) is None


# ---------------------------------------------------------------- findings

def test_no_text_gives_two_passes(tmp_path):
    art, _ = text_art()
    garbled, small = check_text(art, SPEC, P, client_for(tmp_path, answer(notes="no text")))
    assert (garbled.check, garbled.status) == ("text_garbled", "pass")
    assert (small.check, small.status) == ("text_small", "pass")
    assert garbled.measured["model"] == "fake" and garbled.measured["request_sha256"]


def test_small_text_is_measured_not_estimated(tmp_path):
    # 12 px caps at 300 PPI = 2.88 pt, under 0.7 x 6 = 4.2 pt; the model only says where the text is
    art, box = text_art(cap_px=12, ppi=300.0)
    _, small = check_text(art, SPEC, P, client_for(tmp_path, answer(item("SHOP", box=as_fraction(box)))))
    assert small.status == "warn" and small.fixer == "customer"
    assert small.measured["min_cap_height_pt"] == pytest.approx(12 / 300 * 72, abs=0.3)
    needed = 0.2 + 2.8 * 4.2 / small.measured["min_cap_height_pt"]
    assert small.measured["min_size_in_for_text"] == pytest.approx(needed, abs=0.02)


def test_big_text_passes(tmp_path):
    art, box = text_art(cap_px=40, ppi=300.0)  # 9.6 pt caps
    _, small = check_text(art, SPEC, P, client_for(tmp_path, answer(item("SHOP", box=as_fraction(box)))))
    # round letters (S, O) overshoot the cap line by a few percent
    assert small.status == "pass" and small.measured["items"][0]["cap_height_pt"] == pytest.approx(9.6, rel=0.08)


def test_small_text_goes_to_a_person_when_a_bigger_size_would_be_soft(tmp_path):
    art, box = text_art(cap_px=5, ppi=100.0)  # 3.6 pt caps, and 100 PPI cannot grow past ~2 in
    _, small = check_text(art, SPEC, P, client_for(tmp_path, answer(item("SHOP", box=as_fraction(box)))))
    assert small.status == "warn" and small.fixer == "person"
    assert small.measured["min_size_in_for_text"] > small.measured["max_size_in_at_floor"]


def test_unmeasurable_text_is_a_skip(tmp_path):
    art, _ = text_art()
    _, small = check_text(art, SPEC, P, client_for(tmp_path, answer(item("SHOP", box=[0.8, 0.1, 0.95, 0.2]))))
    assert small.status == "skip" and small.measured["reason"] == "no text height could be measured"


def test_garbled_is_decided_by_code_from_the_transcription(tmp_path):
    art, _ = text_art()
    c = client_for(tmp_path, answer(item("FOERST", intended="FOREST"), item("CLUB")))
    garbled, _ = check_text(art, SPEC, P, c)
    assert garbled.status == "fail" and garbled.fixer == "person" and "FOREST" in garbled.message
    assert [i["garbled"] for i in garbled.measured["items"]] == [True, False]
    # mixed case and punctuation are style, not garbling; broken glyphs and unreadable letters are
    c = client_for(tmp_path, answer(item("KiNDNESS", intended="KINDNESS"), item("Salt & Pine", intended="SALT & PINE")))
    assert check_text(art, SPEC, P, c)[0].status == "pass"
    c = client_for(tmp_path, answer(item("CLUB", broken=True), item("SH?P", intended="SHOP")))
    assert [i["garbled"] for i in check_text(art, SPEC, P, c)[0].measured["items"]] == [True, True]


def test_spelled_out_letters_and_the_misspelled_flag_both_count(tmp_path):
    art, _ = text_art()
    autocorrected = {**item("WELCOME"), "letters": "W E L C M E"}  # seen was autocorrected, letters were not
    kept = {**item("KITEN"), "misspelled": True}  # the model kept the typo in `intended` but flagged it
    fine = {**item("Little Crumb"), "letters": "L i t t l e / C r u m b", "misspelled": False}
    c = client_for(tmp_path, answer(autocorrected, kept, fine))
    assert [i["garbled"] for i in check_text(art, SPEC, P, c)[0].measured["items"]] == [True, True, False]


def test_text_small_is_off_by_default(tmp_path, monkeypatch):
    monkeypatch.delenv(vision.TEXT_SMALL_ENV)
    art, box = text_art(cap_px=12)
    findings = check_text(art, SPEC, P, client_for(tmp_path, answer(item("SHOP", box=as_fraction(box)))))
    assert [f.check for f in findings] == ["text_garbled"] and not vision.TEXT_SMALL_DEFAULT


def test_text_small_can_be_turned_off(tmp_path, monkeypatch):
    monkeypatch.setenv(vision.TEXT_SMALL_ENV, "0")
    art, box = text_art(cap_px=12)
    findings = check_text(art, SPEC, P, client_for(tmp_path, answer(item("SHOP", box=as_fraction(box)))))
    assert [f.check for f in findings] == ["text_garbled"]
    assert [f.check for f in vision.skipped("x", {})] == ["text_garbled"]


def test_image_is_the_subject_box_and_scale_is_stated(tmp_path):
    art, _ = text_art()
    c = client_for(tmp_path, answer())
    check_text(art, Spec("die_cut", 3.0, prompt="a sticker that says CLUB"), P, c)
    system, user = c.transport.requests[0]["body"]["messages"]
    assert system["role"] == "system" and "JSON" in system["content"] and "box" in system["content"]
    text, image = user["content"]
    assert "3 in die-cut" in text["text"] and "1.33 in wide" in text["text"] and "CLUB" in text["text"]
    raw = base64.b64decode(image["image_url"]["url"].split(",", 1)[1])
    assert Image.open(io.BytesIO(raw)).size == (400, 200)  # cropped to the subject, not the canvas


def test_opaque_art_sends_the_whole_canvas(tmp_path):
    art, _ = text_art(with_subject=False)
    c = client_for(tmp_path, answer())
    check_text(art, SPEC, P, c)
    url = c.transport.requests[0]["body"]["messages"][1]["content"][1]["image_url"]["url"]
    assert Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1]))).size == (400, 300)


def test_bad_json_gets_one_reminder_then_parses(tmp_path):
    art, _ = text_art()
    c = client_for(tmp_path, "Sure! The text says CLUB.", "```json\n" + answer(item("CLUB")) + "\n```")
    garbled, _ = check_text(art, SPEC, P, c)
    assert garbled.status == "pass" and "CLUB" in garbled.message
    retry = c.transport.requests[1]["body"]["messages"]
    assert retry[-2] == {"role": "assistant", "content": "Sure! The text says CLUB."}
    assert retry[-1] == {"role": "user", "content": REMINDER}


def test_bad_json_twice_is_a_skip_with_the_reason(tmp_path):
    art, _ = text_art()
    c = client_for(tmp_path, "no idea", '{"text": [{"seen": "A"}]}')
    findings = check_text(art, SPEC, P, c)
    assert [f.status for f in findings] == ["skip", "skip"]
    assert findings[0].measured["reason"] == "unreadable answer" and "broken" in findings[0].measured["error"]
    assert len(c.transport.requests) == 2  # exactly one retry


def test_api_error_is_a_skip_with_the_error(tmp_path):
    art, _ = text_art()
    findings = check_text(art, SPEC, P, client_for(tmp_path, {"status": 400, "body": "image too large"}))
    assert [(f.check, f.status) for f in findings] == [("text_garbled", "skip"), ("text_small", "skip")]
    assert findings[0].measured["reason"] == "api error" and "image too large" in findings[0].measured["error"]


def test_budget_exceeded_propagates(tmp_path):
    spend.record("xai", "grok-4.3", 0, 0, 0, 0, 10.0, "earlier")
    art, _ = text_art()
    c = client_for(tmp_path, answer(), price={"in_per_m": 1.25, "out_per_m": 2.5})
    with pytest.raises(BudgetExceeded):
        check_text(art, SPEC, P, c)
    assert c.transport.requests == []


@pytest.mark.parametrize("text, problem", [
    ("", "no JSON object"),
    ("{nope}", "invalid JSON"),
    ('{"words": []}', '"text" list'),
    ('{"text": [{"seen": "A", "broken": "yes"}]}', "broken"),
    ('{"text": [{"seen": "A", "broken": false, "box": [0.5, 0.5, 0.2, 0.9]}]}', "box"),
    ('{"text": [{"seen": "A", "broken": false, "box": [0, 0, 2, 1]}]}', "box"),
])
def test_parse_answer_rejects(text, problem):
    data, why = parse_answer(text)
    assert data is None and problem in why


def test_parse_answer_accepts_missing_box():
    data, why = parse_answer('Here: {"text": [{"seen": "A", "broken": false}], "notes": ""} done')
    assert why == "" and data["text"][0]["seen"] == "A"
