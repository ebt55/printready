"""Agent loop tests on the fake provider. Fix algorithms are replaced by small stand-ins in
guard.FIXES, so the REAL damage guard runs over them and these tests pin the loop, not CORE's
fixes. write_outputs is stubbed except in the one end-to-end test at the bottom."""

import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from printready import agent, guard, llm, pipeline, spend, types, vision
from printready.geometry import cut_mask, long_side_px, ppi_for_long_side
from printready.profile import load_profile
from printready.spend import BudgetExceeded
from printready.types import FixResult, Spec

P = load_profile()
FIXTURES = Path(__file__).parent / "fixtures"
JPG = FIXTURES / "badge-on-white.jpg"  # opaque badge on white: background fail, fixer auto
SPEC = Spec("die_cut", 3.0)
NO_TEXT = {"text": json.dumps({"text": [], "notes": "no text"})}


# ---------------------------------------------------------------- stand-ins for CORE's fixes

def fake_remove_background(art, spec, profile, **kw):
    new = art.copy()
    subject = (art.rgba[..., :3] < 235).any(axis=2)
    new.rgba[..., 3] = np.where(subject, 255, 0).astype(np.uint8)
    new.subject = subject
    new.ppi = ppi_for_long_side(long_side_px(subject), spec, profile)
    return FixResult(new, True, "removed a white background")


def greedy_remove_background(art, spec, profile, **kw):
    """Also erases the left half of the badge: the damage guard must revert it."""
    result = fake_remove_background(art, spec, profile)
    result.art.rgba[:, : art.width // 2, 3] = 0
    result.art.subject[:, : art.width // 2] = False
    return result


def fake_add_border(art, spec, profile, border_in=None, **kw):
    if art.subject is None:
        return FixResult(art.copy(), False, "no subject yet")
    new = art.copy()
    new.border_in = border_in or profile.border_in
    new.cut = cut_mask(art.subject, art.ppi, new.border_in, profile.min_neck_in, profile.speck_max_in2)
    return FixResult(new, True, "added a 0.1 in border")


def fake_noop(art, spec, profile, **kw):
    return FixResult(art.copy(), True, "nothing to do")


@pytest.fixture(autouse=True)
def ledger(tmp_path, monkeypatch):
    monkeypatch.setenv(spend.LEDGER_ENV, str(tmp_path / "ledger.jsonl"))
    monkeypatch.delenv(spend.CAP_ENV, raising=False)


@pytest.fixture
def written():
    return []


@pytest.fixture(autouse=True)
def stand_ins(request, monkeypatch, written):
    if request.node.name.startswith("test_end_to_end"):
        return  # the end-to-end test runs CORE's real fixes and write_outputs
    for name, fn in (("remove_background", fake_remove_background), ("add_border", fake_add_border),
                     ("pad_canvas", fake_noop), ("bridge_islands", fake_noop)):
        monkeypatch.setitem(guard.FIXES, name, fn)

    def write_outputs(run, out_dir):
        written.append(run)
        run.outputs = {**run.outputs, "report": "report.json"}
        return run.outputs

    monkeypatch.setattr(pipeline, "write_outputs", write_outputs)


def call(name, **args):
    return {"name": name, "arguments": args}


def turn(*calls, text=""):
    return {"text": text, "tool_calls": list(calls)}


def fake_client(tmp_path, responses, price=None):
    script = tmp_path / "agent-script.json"
    script.write_text(json.dumps({"responses": responses, "price": price} if price else responses), encoding="utf-8")
    return llm.make_client(f"fake:{script}", sleep=lambda s: None)


def run(tmp_path, responses, price=None, **kw):
    client = fake_client(tmp_path, responses, price)
    events = []
    result = agent.run_agent(JPG, SPEC, P, tmp_path / "out", client, on_event=events.append, **kw)
    return result, client, events


def log_lines(tmp_path):
    return [json.loads(x) for x in (tmp_path / "out" / agent.LOG_NAME).read_text(encoding="utf-8").splitlines()]


MESSAGE = "We removed the white background and added a 0.1 in white border. At 3 in this prints at 100 PPI; " \
          "at 2 in or smaller it stays above 150 PPI. Approve the proof if it looks right."

HAPPY = [
    turn(call("remove_background")),
    turn(call("add_border"), call("check")),
    turn(call("look", view="proof"), call("read_text")),
    NO_TEXT,  # the read_text vision call happens inside turn 3
    turn(call("finish", customer_message=MESSAGE), text="Done."),
]


# ---------------------------------------------------------------- tests

def test_happy_path_tool_loop(tmp_path, written):
    result, client, events = run(tmp_path, HAPPY)
    assert result.mode == "agent" and result.handoff_reason is None
    assert result.customer_message == MESSAGE
    assert [(s.fix, s.ok, s.damaged) for s in result.art.history] == [
        ("remove_background", True, False), ("add_border", True, False)]
    assert result.art.cut is not None
    assert result.before.by_check("background").status == "fail"
    assert result.after.by_check("background").status == "pass"
    assert result.after.by_check("text_garbled").status == "pass"  # read_text findings are in the final report
    assert result.outcome == "fixable"  # a corrective fix ran; resolution is a customer choice
    assert written == [result] and result.spec == SPEC and result.original.history == []
    assert result.outputs["log"] == "log.jsonl" and result.outputs["step-1"] == "step-1-remove_background.png"
    assert result.outputs["look-1"] == "look-1-proof.png"
    assert len(client.transport.requests) == 5


def test_image_goes_back_as_a_user_message_after_the_tool_results(tmp_path):
    _, client, events = run(tmp_path, HAPPY)
    messages = client.transport.requests[4]["body"]["messages"]  # the turn after look
    assistant, tool_look, tool_text, user = messages[-4:]
    ids = [tc["id"] for tc in assistant["tool_calls"]]
    assert assistant["role"] == "assistant" and [tc["function"]["name"] for tc in assistant["tool_calls"]] == ["look", "read_text"]
    assert [tool_look["role"], tool_text["role"]] == ["tool", "tool"]
    assert [tool_look["tool_call_id"], tool_text["tool_call_id"]] == ids
    assert all(isinstance(m["content"], str) and "image_url" not in m["content"] for m in (tool_look, tool_text))
    assert user["role"] == "user"
    label, image, after = user["content"]
    assert label["type"] == "text" and ids[0] in label["text"]
    assert image["type"] == "image_url" and image["image_url"]["url"].startswith("data:image/png;base64,")
    assert after == {"type": "text", "text": agent.AFTER_IMAGE}
    look_turn = next(e for e in events if e["type"] == "turn" and e["n"] == 3)
    assert look_turn["image"] == "look-1-proof.png" and (tmp_path / "out" / look_turn["image"]).exists()
    # the first user message carries the order, the check report and the uploaded art
    text, upload = client.transport.requests[0]["body"]["messages"][1]["content"]
    assert "3 in die-cut" in text["text"] and '"check": "background"' in text["text"]
    assert upload["type"] == "image_url" and (tmp_path / "out" / "look-0-upload.png").exists()


def test_events_follow_the_workbench_schema(tmp_path):
    result, _, events = run(tmp_path, HAPPY)
    for e in events:
        json.dumps(e)  # every event is plain JSON
    kinds = [e["type"] for e in events]
    assert kinds[0] == "findings" and kinds[-1] == "done" and kinds.count("turn") == 4 and kinds.count("step") == 2
    step = next(e for e in events if e["type"] == "step")
    assert step["index"] == 1 and step["preview"] == "step-1-remove_background.png"
    assert step["step"]["fix"] == "remove_background" and step["step"]["ok"] is True
    assert step["step"]["guard"]["metric"] == "damage_frac" and step["step"]["guard"]["passed"] is True
    assert (tmp_path / "out" / step["preview"]).exists()
    t1 = next(e for e in events if e["type"] == "turn")
    assert {"n", "text", "tool_calls", "tokens", "cost_usd", "latency_ms", "image"} <= set(t1)
    assert t1["tool_calls"][0]["name"] == "remove_background" and t1["tool_calls"][0]["result"] == "remove_background: ok"
    assert events[-1]["result"]["outcome"] == result.outcome


def test_log_jsonl_has_every_call_and_turn(tmp_path):
    run(tmp_path, HAPPY)
    lines = log_lines(tmp_path)
    kinds = [x["type"] for x in lines]
    assert kinds[0] == "start" and kinds[-1] == "end"
    assert kinds.count("call") == 5 and kinds.count("turn") == 4  # 4 agent turns + 1 vision call
    calls = [x for x in lines if x["type"] == "call"]
    assert [c["purpose"] for c in calls] == ["agent", "agent", "agent", "vision", "agent"]
    assert all(c["request_sha256"] and c["model_returned"] == "fake" for c in calls)
    turns = [x for x in lines if x["type"] == "turn"]
    assert all({"request_sha256", "model", "tokens", "cost_usd", "latency_ms", "tool_calls"} <= set(t) for t in turns)
    # each call is logged before the turn that used its result
    assert kinds.index("call") < kinds.index("turn")
    assert lines[-1]["outcome"] == "fixable" and lines[-1]["handoff"] is False


def test_outcome_comes_from_types_outcome_not_the_model(tmp_path, monkeypatch):
    seen = []

    def spy(art, final, handoff=False):
        seen.append((art, final, handoff))
        return types.outcome(art, final, handoff)

    monkeypatch.setattr(agent, "outcome", spy)
    garbled = {"text": json.dumps({"text": [{"seen": "STIKCER", "intended": "STICKER", "broken": False,
                                             "box": None}], "notes": ""})}
    script = [turn(call("remove_background"), call("add_border")), turn(call("read_text")), garbled,
              turn(call("finish", customer_message="All good, it is ready to print. Approve the proof."),
                   text="The outcome is ready.")]
    result, _, _ = run(tmp_path, script)
    (art, final, handoff), = seen
    assert handoff is False and art is result.art and final is result.after
    assert final.by_check("text_garbled").status == "fail"
    assert result.outcome == "needs_person"  # the model said ready and finished; the rule says otherwise
    assert "person" in result.customer_message  # so the model's "approve" message is not sent
    assert any("draft message" in n for n in result.person_notes)


def test_unknown_tool_and_bad_json_are_answered_as_tool_errors(tmp_path):
    script = [
        {"tool_calls": [{"name": "regenerate", "arguments": {}}, {"name": "look", "arguments": "{view: proof"},
                        {"name": "look", "arguments": {"view": "sideways"}}]},
        turn(call("handoff", reason="unsure", person_notes="I could not render the proof.")),
    ]
    result, client, _ = run(tmp_path, script)
    tool_msgs = [m for m in client.transport.requests[1]["body"]["messages"] if m["role"] == "tool"]
    errors = [json.loads(m["content"])["error"] for m in tool_msgs]
    assert "unknown tool 'regenerate'" in errors[0]
    assert "not valid JSON" in errors[1]
    assert "view must be" in errors[2]
    assert result.handoff_reason == "unsure" and result.person_notes[0] == "I could not render the proof."
    assert any(n.startswith("background fail (auto)") for n in result.person_notes)  # the checks' own notes follow
    assert result.outcome == "needs_person" and result.art.history == []


def test_turn_limit_hands_off(tmp_path):
    result, client, events = run(tmp_path, [turn(call("check"))] * agent.MAX_TURNS)
    assert len(client.transport.requests) == agent.MAX_TURNS
    last = client.transport.requests[-1]["body"]["messages"]
    assert {"role": "user", "content": agent.LAST_TURN} in last
    assert result.handoff_reason == "turn limit" and result.outcome == "needs_person"
    assert "person" in result.customer_message  # the shared needs_person template, not a model message
    assert sum(e["type"] == "turn" for e in events) == agent.MAX_TURNS


def test_text_only_reply_is_nudged(tmp_path):
    script = [{"text": "I think this needs a background removal."}, turn(call("handoff", reason="r", person_notes="n"))]
    _, client, _ = run(tmp_path, script)
    assert client.transport.requests[1]["body"]["messages"][-1] == {"role": "user", "content": agent.NUDGE}


def test_api_error_ends_the_run_as_handoff_error(tmp_path):
    result, client, events = run(tmp_path, [turn(call("remove_background")), {"status": 400, "body": "bad image"}])
    assert result.handoff_reason == "error" and result.outcome == "needs_person"
    assert "bad image" in result.person_notes[0]
    assert [s.fix for s in result.art.history] == ["remove_background"]  # work done so far is kept
    lines = log_lines(tmp_path)
    assert [c["status"] for c in lines if c["type"] == "call"] == ["ok", "error"]
    assert lines[-2]["type"] == "turn" and lines[-2]["error"].startswith("error:")
    assert events[-1]["type"] == "done"


def test_budget_exceeded_before_the_first_call_is_a_handoff(tmp_path):
    spend.record("xai", "grok-4.3", 0, 0, 0, 0, 9.999, "earlier")
    result, client, _ = run(tmp_path, HAPPY, price={"in_per_m": 1.25, "out_per_m": 2.5})
    assert client.transport.requests == []  # refused before anything was sent
    assert result.handoff_reason == "budget" and result.outcome == "needs_person" and result.cost_usd == 0.0
    assert [c["status"] for c in log_lines(tmp_path) if c["type"] == "call"] == ["budget"]


def test_budget_exceeded_inside_read_text_is_a_handoff(tmp_path, monkeypatch):
    def over_budget(*a, **kw):
        raise BudgetExceeded("cap reached")

    monkeypatch.setattr(vision, "check_text", over_budget)
    script = [turn(call("remove_background"), call("read_text"), call("add_border"))]
    result, client, _ = run(tmp_path, script)
    assert result.handoff_reason == "budget" and len(client.transport.requests) == 1
    assert [s.fix for s in result.art.history] == ["remove_background"]  # add_border came after the stop


def test_finish_needs_a_border_and_a_short_message(tmp_path):
    long_message = " ".join(["word"] * 81)
    script = [
        turn(call("finish", customer_message="Looks good. Approve the proof.")),
        turn(call("remove_background"), call("add_border"), call("finish", customer_message=long_message)),
        turn(call("finish", customer_message="Removed the background. Approve the proof.")),
    ]
    result, client, _ = run(tmp_path, script)
    first = [json.loads(m["content"]) for m in client.transport.requests[1]["body"]["messages"] if m["role"] == "tool"]
    assert "no cut line yet" in first[0]["error"]
    second = [json.loads(m["content"]) for m in client.transport.requests[2]["body"]["messages"] if m["role"] == "tool"]
    assert "81 words" in second[-1]["error"]
    assert result.customer_message == "Removed the background. Approve the proof." and result.handoff_reason is None


def test_damaged_fix_is_reverted_by_the_guard_and_recorded(tmp_path, monkeypatch):
    monkeypatch.setitem(guard.FIXES, "remove_background", greedy_remove_background)
    script = [turn(call("remove_background")), turn(call("handoff", reason="damaged", person_notes="guard reverted"))]
    result, client, _ = run(tmp_path, script)
    (step,) = result.art.history
    assert (step.fix, step.ok, step.damaged) == ("remove_background", False, True)
    assert np.array_equal(result.art.rgba, result.original.rgba) and result.art.subject is None
    tool = json.loads(client.transport.requests[1]["body"]["messages"][-1]["content"])
    assert tool["ok"] is False and tool["damaged"] is True and "Reverted" in tool["note"]
    assert result.outcome == "needs_person"


def test_a_fix_that_crashes_is_a_refused_step(tmp_path, monkeypatch):
    def boom(art, spec, profile, **kw):
        raise ValueError("cannot")

    monkeypatch.setitem(guard.FIXES, "pad_canvas", boom)
    script = [turn(call("pad_canvas")), turn(call("handoff", reason="r", person_notes="n"))]
    result, _, _ = run(tmp_path, script)
    (step,) = result.art.history
    assert step.fix == "pad_canvas" and not step.ok and "ValueError: cannot" in step.note


def test_calls_after_finish_in_the_same_turn_are_ignored(tmp_path):
    script = [turn(call("remove_background"), call("add_border"),
                   call("finish", customer_message="Done. Approve the proof."), call("pad_canvas"))]
    result, client, events = run(tmp_path, script)
    assert [s.fix for s in result.art.history] == ["remove_background", "add_border"]
    assert events[[e["type"] for e in events].index("turn")]["tool_calls"][-1]["result"] == "ignored"


def test_paid_run_cost_sums_every_call(tmp_path):
    result, client, _ = run(tmp_path, HAPPY, price={"in_per_m": 1.25, "cached_per_m": 0.2, "out_per_m": 2.5})
    assert result.cost_usd == pytest.approx(client.cost_usd) and result.cost_usd > 0
    assert spend.ledger_total() == pytest.approx(result.cost_usd, abs=1e-5)


def test_system_prompt_names_rule_sources_and_limits():
    text = agent.system_prompt(P)
    assert "300 PPI" in text and "[Sticker Mule FAQ]" in text and "[convention]" in text
    assert "80 words" in text and f"at most {agent.MAX_TURNS}" in text and "$" not in text
    assert {t["function"]["name"] for t in agent.TOOLS} == {
        "check", "look", "remove_background", "pad_canvas", "add_border", "bridge_islands", "fit_shape",
        "read_text", "finish", "handoff"}
    assert "rounded rectangle" in text and "offer" in text  # scenes get a whole-image sticker and a person option


def test_a_scene_becomes_a_rounded_rectangle_with_cores_fit_shape(tmp_path, written):
    yy, xx = np.mgrid[0:300, 0:300]
    scene = np.dstack([xx * 255 // 299, yy * 255 // 299, np.full_like(xx, 120), np.full_like(xx, 255)]).astype(np.uint8)
    path = tmp_path / "scene.png"
    Image.fromarray(scene).save(path)
    message = "Your art is a full scene, so we made it a rounded-rectangle sticker of the whole image. A person can cut out part of the art instead. Approve the proof."
    script = [turn(call("fit_shape"), call("check")), turn(call("finish", customer_message=message))]
    client = fake_client(tmp_path, script)
    result = agent.run_agent(path, SPEC, P, tmp_path / "out", client)
    assert result.before.by_check("background").fixer == "person"
    assert [s.fix for s in result.art.history] == ["fit_shape"] and result.art.shape == "rounded_rect"
    assert result.after.by_check("product_fit").fixer == "customer"
    assert result.outcome == "fixable" and result.customer_message == message


def test_a_file_that_does_not_open_makes_no_model_call(tmp_path, written):
    bad = tmp_path / "not-an-image.png"
    bad.write_bytes(b"hello")
    client = fake_client(tmp_path, [turn(call("check"))])
    result = agent.run_agent(bad, SPEC, P, tmp_path / "out", client)
    assert client.transport.requests == [] and result.art is None
    assert result.before.by_check("file").status == "fail" and result.outcome == "needs_person"
    assert written == [result]


def test_end_to_end_with_cores_fixes_guard_and_outputs(tmp_path):
    result, _, _ = run(tmp_path, HAPPY)
    out = tmp_path / "out"
    assert [(s.fix, s.ok) for s in result.art.history] == [("remove_background", True), ("add_border", True)]
    assert result.outcome == types.outcome(result.art, result.after, handoff=False) == "fixable"
    for name in ("report.json", "fixed.png", "cutline.svg", "proof.png", "overlay.png", "customer_message.md",
                 "report.html", "log.jsonl", "step-1-remove_background.png", "look-1-proof.png"):
        assert (out / name).exists(), name
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert report["mode"] == "agent" and report["outputs"]["log"] == "log.jsonl"
    assert (out / "customer_message.md").read_text(encoding="utf-8").strip() == MESSAGE
