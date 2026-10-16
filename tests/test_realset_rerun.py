"""PREREG addendum 1 tooling, offline: which runs qualify, settled-never-rerun, the deadline, and
that results/realset/<split>/ is never written by a rerun."""

import base64
import io
import json
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
import pytest
from PIL import Image

from printready import prereg, realset
from printready.cli import main
from printready.llm import ChatClient, FakeTransport
from printready.realset import Paths, read_jsonl, sample_shas
from printready.realset import evaluate as ev
from printready.realset import gen, label, rerun, runs
from printready.spend import Price

MODELS = ["xai:grok-imagine-image", "xai:grok-imagine-image-2.0"]
PRICE = Price(in_per_m=1.25, out_per_m=2.5)
NO_TEXT = {"text": json.dumps({"text": [], "notes": "no text"})}
HANDOFF = {"tool_calls": [{"name": "handoff", "arguments": {"reason": "test", "person_notes": "n"}}]}
DEADLINE = "2026-10-19T18:00+05:30"
BEFORE = datetime(2026, 10, 19, 12, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
AFTER = datetime(2026, 10, 19, 18, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))


def png(seed):
    img = np.full((240, 240, 3), 255, np.uint8)
    cv2.circle(img, (120, 120), 70 + seed % 20, (40 + 9 * seed % 200, 90, 160), -1)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


def client(model, responses, calls=None):
    c = ChatClient(model, FakeTransport(responses), price=PRICE, sleep=lambda s: None)
    if calls is not None:
        calls.append(c)
    return c


@pytest.fixture
def test_split(tmp_path, monkeypatch):
    """A test split of 6 images with original runs: rules vision got 429 on 2 images (and 403 on
    1), answered on the rest; agent got 403 on all but one, which billed a call then hit 429."""
    (tmp_path / "realset").mkdir()
    (tmp_path / "realset" / "prompts.txt").write_text("a cat\na dog\na fox\n", encoding="utf-8")
    monkeypatch.setenv(realset.ROOT_ENV, str(tmp_path))
    monkeypatch.setattr(prereg, "require_verified", lambda root=None: None)
    paths = Paths.for_split("test")
    images = iter(range(1, 99))
    gen.generate(paths, MODELS, log=lambda s: None, client_factory=lambda m: client(
        m, [{"b64_json": base64.b64encode(png(next(images))).decode()} for _ in range(3)]))
    items = runs.select(paths, sample=False)
    vision = iter([[{"status": 429}] * 4, [{"status": 429}] * 4, [{"status": 403}], [NO_TEXT], [NO_TEXT], [NO_TEXT]])
    runs.run_split(paths, "rules", items, client_factory=lambda: client("xai:grok-4.3", next(vision)), log=lambda s: None)
    agent = iter([[{"status": 403}]] * 5 + [[{"tool_calls": [{"name": "check", "arguments": {}}]}] + [{"status": 429}] * 4])
    runs.run_split(paths, "agent", items, client_factory=lambda: client("xai:grok-4.3", next(agent)), log=lambda s: None)
    return paths


def originals(paths, mode):
    return {r["image"]: r for r in read_jsonl(paths.runs(mode))}


def snapshot(paths):
    return {p: p.read_bytes() for p in (paths.root / "results" / "realset" / "test").rglob("*") if p.is_file()
            and p.name != rerun.LIST_NAME}


def test_only_runs_whose_every_call_got_403_or_429_with_zero_tokens_are_listed(test_split, capsys):
    paths = test_split
    assert main(["realset", "rerun-list", "--split", "test", "--deadline", DEADLINE]) == 0
    assert "rules: 3 of 6" in capsys.readouterr().out
    deadline, listed = rerun.read_list(paths)
    assert deadline.isoformat() == "2026-10-19T18:00:00+05:30"
    assert len(listed["rules"]) == 3 and len(listed["agent"]) == 5
    rules, agent = originals(paths, "rules"), originals(paths, "agent")
    assert all(rules[s]["cost_usd"] == 0 for s in listed["rules"])
    billed_agent = [s for s, r in agent.items() if r["cost_usd"] > 0]
    assert billed_agent and not set(billed_agent) & set(listed["agent"])  # one call billed: never listed
    text = (paths.results / rerun.LIST_NAME).read_text()
    assert "# deadline: 2026-10-19T18:00+05:30" in text and text.count("\nrules ") == 3


def test_a_hand_edited_list_with_a_billed_run_is_refused(test_split):
    paths = test_split
    rerun.write_list(paths, DEADLINE)
    billed = next(s for s, r in originals(paths, "rules").items() if r["cost_usd"] > 0)
    with (paths.results / rerun.LIST_NAME).open("a") as fh:
        fh.write(f"rules {billed}\n")
    with pytest.raises(rerun.RerunError, match="do not qualify"):
        rerun.rerun(paths, "rules", lambda m: client(m, [NO_TEXT]), now=BEFORE, log=lambda s: None)


def test_rerun_settles_on_the_first_billed_attempt_and_never_touches_the_original_results(test_split):
    paths = test_split
    rerun.write_list(paths, DEADLINE)
    before = snapshot(paths)
    calls = []
    # first invocation: one image still gets 429 (no tokens), two answer
    answers = iter([[{"status": 429}] * 4, [NO_TEXT], [NO_TEXT]])
    records = rerun.rerun(paths, "rules", lambda m: client(m, next(answers), calls), now=BEFORE, log=lambda s: None)
    assert [r["billed"] for r in records] == [False, True, True] and [r["attempt"] for r in records] == [1, 1, 1]
    rows = read_jsonl(rerun.rerun_runs(paths, "rules"))
    assert len(rows) == 2 and all(r["attempt"] == 1 and r["fixed_matches_original"] for r in rows)
    assert all(r["out_dir"].startswith("results/realset/test-rerun/rules/") for r in rows)
    # second invocation: only the unsettled one is attempted, as attempt 2
    records = rerun.rerun(paths, "rules", lambda m: client(m, [NO_TEXT], calls), now=BEFORE, log=lambda s: None)
    assert [(r["attempt"], r["billed"]) for r in records] == [(2, True)] and len(calls) == 4
    # third: everything settled, nothing is called
    assert rerun.rerun(paths, "rules", lambda m: client(m, [NO_TEXT], calls), now=BEFORE, log=lambda s: None) == []
    assert len(calls) == 4 and rerun.status(paths, "rules")["pending"] == []
    assert snapshot(paths) == before  # results/realset/test/ is byte-for-byte unchanged


def test_after_the_deadline_unsettled_runs_become_a_final_error_handoff(test_split):
    paths = test_split
    rerun.write_list(paths, DEADLINE)
    rerun.rerun(paths, "agent", lambda m: client(m, [{"status": 403}]), now=BEFORE, log=lambda s: None)
    assert all(not a["billed"] for a in read_jsonl(rerun.rerun_root(paths) / "attempts.jsonl"))
    calls = []
    assert rerun.rerun(paths, "agent", lambda m: client(m, [HANDOFF], calls), now=AFTER, log=lambda s: None) == []
    assert calls == []  # past the deadline nothing is attempted
    rows = read_jsonl(rerun.rerun_runs(paths, "agent"))
    assert len(rows) == 5 and {(r["outcome"], r["handoff_reason"], r["rerun_final"], r["attempt"]) for r in rows} == {
        ("needs_person", "error", "deadline", 1)}
    rerun.rerun(paths, "agent", lambda m: client(m, [HANDOFF], calls), now=AFTER, log=lambda s: None)
    assert len(read_jsonl(rerun.rerun_runs(paths, "agent"))) == 5  # recorded once


def test_agent_rerun_settles_with_any_billed_call(test_split):
    paths = test_split
    rerun.write_list(paths, DEADLINE)
    rerun.rerun(paths, "agent", lambda m: client(m, [HANDOFF]), now=BEFORE, log=lambda s: None)
    rows = read_jsonl(rerun.rerun_runs(paths, "agent"))
    assert len(rows) == 5 and {r["handoff_reason"] for r in rows} == {"test"} and all(r["cost_usd"] > 0 for r in rows)
    assert all((paths.root / r["out_dir"] / "log.jsonl").exists() for r in rows)


def test_eval_with_rerun_reports_both_sets_side_by_side(test_split):
    paths = test_split
    rerun.write_list(paths, DEADLINE)
    rerun.rerun(paths, "rules", lambda m: client(m, [NO_TEXT]), now=BEFORE, log=lambda s: None)
    rerun.rerun(paths, "agent", lambda m: client(m, [HANDOFF]), now=BEFORE, log=lambda s: None)
    realset.append_jsonl(paths.labels, [{"ts": "t", "pass": 1, "image": s, "proof": None, "label": "fixable_diecut"}
                                        for s in sample_shas(read_jsonl(paths.manifest))])
    s = ev.evaluate(paths, with_rerun=True)
    assert s["modes"]["rules"]["agree"] == 3 and s["rerun"]["modes"]["rules"]["agree"] == 6
    assert s["rerun"]["label"] == "rerun (PREREG addendum 1)"
    assert s["rerun"]["reruns"]["rules"] == {"listed": 3, "attempts": 3, "settled": 3, "error_at_deadline": 0,
                                             "still_pending": 0, "fixed_matches_original": 3, "fixed_differs": 0}
    assert s["modes"]["agent"]["two_class"] == {"prereg": 0, "scene_as_person": 0}
    md = (paths.results / "eval.md").read_text()
    assert "## Preregistered" in md and "## Rerun (PREREG addendum 1)" in md and "post hoc, exploratory" in md
    assert "rerun" not in ev.evaluate(paths)  # without the flag: preregistered numbers only


def test_pass_2_includes_rerun_proofs_deduped_and_blinded(test_split):
    paths = test_split
    rerun.write_list(paths, DEADLINE)
    rerun.rerun(paths, "rules", lambda m: client(m, [NO_TEXT]), now=BEFORE, log=lambda s: None)
    data = label.pass2_items(paths)
    mapping = json.loads((paths.data / "label-pass2-mapping.json").read_text())
    # 3 proofs from the original rules runs that answered, 3 from the reruns of the ones that did not
    sources = {m["source"] for entries in mapping.values() for m in entries}
    assert sources == {"original", "rerun"} and len(data["items"]) == len(mapping) == 6
    assert "rerun" not in json.dumps(data) and "rules" not in json.dumps(data)
