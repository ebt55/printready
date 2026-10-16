"""Rules mode end to end on small synthetic images written to disk."""

import json

import cv2
import numpy as np
import pytest
from PIL import Image

from printready.pipeline import run_rules, write_outputs
from printready.profile import load_profile
from printready.types import Finding, Report, RunResult, Spec

P = load_profile()
SS = 4


def disc_layer(h, w, circles, colour=(200, 60, 40)):
    big = np.zeros((h * SS, w * SS), np.uint8)
    for cx, cy, r in circles:
        cv2.circle(big, (round(cx * SS), round(cy * SS)), round(r * SS), 255, -1)
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., :3] = colour
    rgba[..., 3] = cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)
    return rgba


def flatten(rgba, bg):
    a = rgba[..., 3:4] / 255.0
    rgb = (rgba[..., :3] * a + np.asarray(bg, float) * (1 - a)).round().astype(np.uint8)
    return rgb


def save(tmp_path, name, array):
    path = tmp_path / name
    Image.fromarray(array).save(path)
    return path


DISC = disc_layer(320, 320, [(160, 160, 100)])  # 200 px subject
SIZE_400PPI = Spec("die_cut", 200 / 400 + 0.2)


def run(tmp_path, name, array, spec=SIZE_400PPI, **kw):
    events = []
    result = run_rules(save(tmp_path, name, array), spec, P, tmp_path / "out" / name, on_event=events.append, **kw)
    return result, events


def test_solid_background_is_fixable_with_outputs(tmp_path):
    result, events = run(tmp_path, "white.png", flatten(DISC, (255, 255, 255)))
    assert result.outcome == "fixable"
    assert [s.fix for s in result.art.history] == ["remove_background", "add_border"]
    assert result.after.status() == "pass"
    out = tmp_path / "out" / "white.png"
    for name in ("report.json", "fixed.png", "cutline.svg", "proof.png", "overlay.png", "customer_message.md", "report.html"):
        assert (out / name).exists(), name
    assert set(result.outputs) >= {"fixed", "cutline", "proof", "overlay", "customer_message", "report", "html", "step-1"}
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["outcome"] == "fixable" and data["spec"]["size_in"] == pytest.approx(0.7)
    assert Report.from_dict(data["after"]).status() == "pass"
    assert [h["fix"] for h in data["history"]] == ["remove_background", "add_border"]
    assert "removed the plain background" in result.customer_message
    assert len(result.customer_message.split()) <= 80
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "data:image/png;base64," in html and "http" not in html.replace("http://www.w3.org", "")


def test_event_order_and_payloads(tmp_path):
    result, events = run(tmp_path, "white.png", flatten(DISC, (255, 255, 255)))
    kinds = [e["type"] for e in events]
    assert kinds == ["findings", "step", "step", "findings", "done"]
    assert [e.get("stage") for e in events if e["type"] == "findings"] == ["before", "after"]
    step = events[1]
    assert step["step"]["fix"] == "remove_background" and step["preview"] == "step-1-remove_background.png"
    assert (tmp_path / "out" / "white.png" / step["preview"]).exists()
    json.dumps(events)  # every payload is JSON-ready
    assert events[-1]["result"]["outcome"] == result.outcome


def test_clean_alpha_art_is_ready(tmp_path):
    result, _ = run(tmp_path, "clean.png", DISC)
    assert result.outcome == "ready"
    assert [s.fix for s in result.art.history] == ["add_border"]


def test_gradient_background_becomes_a_rounded_rectangle(tmp_path):
    gradient = np.repeat(np.linspace(0, 255, 320)[None, :, None], 320, axis=0).repeat(3, axis=2)
    result, _ = run(tmp_path, "gradient.png", flatten(DISC, gradient), spec=Spec("die_cut", 3.0))
    assert result.outcome == "fixable"
    assert [(s.fix, s.ok) for s in result.art.history] == [("fit_shape", True)]
    assert result.art.shape == "rounded_rect" and result.art.ppi == pytest.approx(320 / (3.0 + 2 * P.bleed_in))
    fit = result.after.by_check("product_fit")
    assert (fit.status, fit.fixer) == ("warn", "customer")
    for check in ("background", "soft_alpha", "edge_crop", "islands"):
        f = result.after.by_check(check)
        assert (f.status, f.measured["applies"]) == ("pass", False)
    assert "rounded-rectangle sticker" in result.customer_message and "ask a person" in result.customer_message
    out = tmp_path / "out" / "gradient.png"
    assert "<rect " in (out / "cutline.svg").read_text(encoding="utf-8") and (out / "proof.png").exists()


def test_two_parts_with_gap_are_bridged(tmp_path):
    ppi, gap = 200, 0.3 * 200
    rgba = disc_layer(240, round(120 + 200 + gap), [(110, 120, 50), (110 + 100 + gap, 120, 50)])
    spec = Spec("die_cut", (200 + gap) / ppi + 0.2)
    result, _ = run(tmp_path, "two.png", rgba, spec=spec)
    assert result.outcome == "fixable"
    fixes = [s.fix for s in result.art.history if s.ok]
    assert "bridge_islands" in fixes and result.before.by_check("islands").fixer == "auto"
    assert result.after.by_check("islands").status == "pass"


def test_low_resolution_customer_vs_person(tmp_path):
    result, _ = run(tmp_path, "soft.png", DISC, spec=Spec("die_cut", 200 / 120 + 0.2))  # 120 PPI
    assert result.outcome == "fixable"
    res = result.after.by_check("resolution")
    assert (res.status, res.fixer) == ("fail", "customer")
    assert "choose a smaller size" in result.customer_message
    tiny = disc_layer(100, 100, [(50, 50, 40)])  # 80 px: even 1 in is under 150 PPI
    result, _ = run(tmp_path, "tiny.png", tiny, spec=Spec("die_cut", 80 / 60 + 0.2))
    assert result.outcome == "needs_person"


def test_art_touching_edge_is_padded(tmp_path):
    rgba = np.zeros((300, 300, 4), np.uint8)
    rgba[0:150, 140:160] = (10, 120, 200, 255)  # touches the top for 0.05 in at 400 PPI
    result, _ = run(tmp_path, "edge.png", rgba, spec=Spec("die_cut", 150 / 400 + 0.2))
    assert [s.fix for s in result.art.history] == ["pad_canvas", "add_border"]
    assert result.outcome == "fixable" and result.art.offset[1] > 0
    assert result.after.by_check("edge_crop").status == "pass"


def test_undecodable_file_is_a_file_fail(tmp_path):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"\x89PNG nope")
    events = []
    result = run_rules(bad, SIZE_400PPI, P, tmp_path / "out", on_event=events.append)
    assert result.outcome == "needs_person" and result.art is None
    assert result.after.by_check("file").status == "fail"
    assert [e["type"] for e in events] == ["findings", "done"]
    assert (tmp_path / "out" / "report.json").exists() and (tmp_path / "out" / "report.html").exists()


def test_refused_fix_hands_finding_to_person(tmp_path, monkeypatch):
    import printready.guard as guard
    from printready.fixes._common import refuse

    monkeypatch.setitem(guard.FIXES, "bridge_islands", lambda art, spec, profile: refuse(art, "Test refusal."))
    gap = 0.4 * 200  # joins only with a wider border, which the refused bridge would have grown
    rgba = disc_layer(240, round(120 + 200 + gap), [(110, 120, 50), (110 + 100 + gap, 120, 50)])
    result, _ = run(tmp_path, "two.png", rgba, spec=Spec("die_cut", (200 + gap) / 200 + 0.2))
    islands = result.after.by_check("islands")
    assert (islands.status, islands.fixer) == ("fail", "person") and "Test refusal." in islands.message
    assert result.outcome == "needs_person"


def test_refused_background_removal_falls_back_to_the_whole_image(tmp_path, monkeypatch):
    import printready.guard as guard
    from printready.fixes._common import refuse

    monkeypatch.setitem(guard.FIXES, "remove_background", lambda art, spec, profile: refuse(art, "Test refusal."))
    result, _ = run(tmp_path, "white.png", flatten(DISC, (255, 255, 255)))
    assert [(s.fix, s.ok) for s in result.art.history] == [("remove_background", False), ("fit_shape", True)]
    assert result.outcome == "fixable"


def test_vision_runs_only_with_a_client(tmp_path, monkeypatch):
    import printready.vision as vision

    calls = []

    def check_text(art, spec, profile, client):
        calls.append(client)
        return [Finding("text_small", "warn", "The text is small at this size.", {"cap_height_pt": 3.1}, "customer")]

    monkeypatch.setattr(vision, "check_text", check_text, raising=False)
    result, _ = run(tmp_path, "clean.png", DISC)
    assert calls == [] and result.outcome == "ready"
    result, _ = run(tmp_path, "clean2.png", DISC, client=object())
    assert len(calls) == 1 and result.after.by_check("text_small").status == "warn"
    assert result.outcome == "fixable"

    monkeypatch.setattr(vision, "check_text", lambda *a: (_ for _ in ()).throw(RuntimeError("API down")), raising=False)
    result, _ = run(tmp_path, "clean3.png", DISC, client=object())
    assert result.after.by_check("text_garbled").status == "skip" and result.outcome == "needs_person"


def test_write_outputs_requires_spec_and_round_trips(tmp_path):
    result, _ = run(tmp_path, "white.png", flatten(DISC, (255, 255, 255)))
    again = RunResult(**{**result.__dict__, "outputs": {}, "original": None})  # reload original from meta path
    outputs = write_outputs(again, tmp_path / "again")
    assert (tmp_path / "again" / outputs["overlay"]).exists()
    with pytest.raises(ValueError):
        write_outputs(RunResult(**{**result.__dict__, "spec": None}), tmp_path / "nospec")


def test_soft_shadow_still_needs_person_after_border(tmp_path):
    # Bench regression: the white border used to halve the soft-alpha distances and hide the shadow.
    yy, xx = np.indices((320, 320))
    rgba = np.zeros((320, 320, 4), np.uint8)
    rgba[..., :3] = 30
    rgba[..., 3] = np.clip(255 * (1 - (np.hypot(xx - 160, yy - 160) - 90) / 24), 0, 255).astype(np.uint8)  # 0.06 in at 400 PPI
    result, _ = run(tmp_path, "shadow.png", rgba, spec=Spec("die_cut", 204 / 400 + 0.2))
    assert [s.fix for s in result.art.history] == ["add_border"]
    soft = result.after.by_check("soft_alpha")
    assert (soft.status, soft.fixer) == ("warn", "person")
    assert soft.measured == result.before.by_check("soft_alpha").measured
    assert result.outcome == "needs_person"


def test_starry_background_falls_back_to_a_rounded_rectangle(tmp_path):
    rng = np.random.default_rng(5)
    rgb = flatten(DISC, (20, 25, 60))
    for y, x in zip(rng.integers(12, 308, 600), rng.integers(12, 308, 600)):
        if np.hypot(x - 160, y - 160) > 110:
            rgb[y:y + 2, x:x + 2] = 250
    result, _ = run(tmp_path, "stars.png", rgb, spec=Spec("die_cut", 3.0))
    step = result.art.history[0]
    assert (step.fix, step.ok) == ("remove_background", False) and step.measured["specks"] > 250
    assert "not one flat colour" in step.note
    assert result.art.history[1].fix == "fit_shape" and result.outcome == "fixable"
    assert any("remove_background was refused" in note for note in result.person_notes)
