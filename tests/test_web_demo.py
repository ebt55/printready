"""The demo folder and the scripted demo model (real pipeline, scripted model, no network)."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest

from printready.web import demo, demo_script
from printready.web.paths import demo_dir, samples_dir
from printready.web.samples import SAMPLES, draw_bolt

OUTCOMES = {"ready", "fixable", "needs_person"}


def test_samples_manifest_matches_the_files():
    manifest = demo.load_samples(include_real=False)
    assert {s["id"] for s in manifest} <= {s.id for s in SAMPLES}
    for s in manifest:
        assert (samples_dir() / s["file"]).is_file()
    # with the real examples: every image resolves, and the drawn samples come first
    everything = demo.load_samples()
    assert everything[: len(manifest)] == manifest
    for s in everything:
        assert demo.sample_path(s).is_file(), s["id"]


def test_real_examples_are_dev_set_grok_runs():
    """The "Real Grok examples" are saved live runs from the DEV split only (blinding), labelled as such."""
    from printready.web import demo_real

    assert demo_real.REAL_SPLIT == "dev"
    real = [s for s in demo.load_samples() if s.get("group") == "real"]
    if not real:
        pytest.skip("no real examples in the demo folder (built from results/realset/dev by --rebuild-demo)")
    runs = {k: v for k, v in demo.load_index().get("runs", {}).items() if v.get("real")}
    for s in real:
        assert s["note"] == "real Grok output, dev set" and s["base"] == "demo"
        assert "test" not in Path(s["file"]).parts
    for key, entry in runs.items():
        run_dir = demo_dir() / entry["dir"]
        events = demo.read_events(run_dir)
        assert events[-1]["type"] == "done" and events[-1]["result"]["mode"] == entry["mode"], key
        ts = [e["_t"] for e in events]
        assert ts == sorted(ts), key  # a replay streams in recorded order
        if entry["mode"] == "agent":
            turns = [e for e in events if e["type"] == "turn"]
            assert turns and all(t.get("model", "").startswith("grok") for t in turns), key
            assert all("tokens" in t and "latency_ms" in t for t in turns), key


def test_samples_are_drawn_deterministically():
    def digest():
        buf = io.BytesIO()
        draw_bolt().save(buf, "PNG")
        return hashlib.sha256(buf.getvalue()).hexdigest()

    assert digest() == digest()


def test_demo_folder_holds_saved_runs():
    index = demo.load_index()
    assert index.get("runs"), "run `printready serve --rebuild-demo`"
    for key, entry in index["runs"].items():
        if entry.get("real"):
            continue  # saved live runs: checked in test_real_examples_are_dev_set_grok_runs
        run_dir = demo_dir() / entry["dir"]
        events = demo.read_events(run_dir)
        assert events and events[-1]["type"] == "done", key
        assert all("_t" in e for e in events)
        result = events[-1]["result"]
        assert result["outcome"] in OUTCOMES and result["mode"] == entry["mode"]
        assert (run_dir / "fixed.png").is_file() and (run_dir / "report.json").is_file()
        if entry["mode"] == "agent":
            turns = [e for e in events if e["type"] == "turn"]
            assert turns and not any(t.get("error") for t in turns), key  # the script never ran dry


def test_canned_lookup_requires_an_exact_match():
    entry = next(e for e in demo.load_index()["runs"].values() if not e.get("real"))
    assert demo.canned_run_dir(entry["sample"], entry["mode"], entry["size_in"], entry["vision"]) is not None
    assert demo.canned_run_dir(entry["sample"], entry["mode"], entry["size_in"] + 1, entry["vision"]) is None


def test_scripted_agent_runs_the_real_tools(tmp_path):
    sample = next(s for s in demo.load_samples() if s["id"] == "bolt")
    events = []
    result = demo.run_demo_image(samples_dir() / sample["file"], tmp_path, "agent", events.append,
                                 vision=sample.get("vision"), agent_opts=sample.get("agent"), speed=0)
    assert result["outcome"] in OUTCOMES and result["mode"] == "agent"
    turns = [e for e in events if e["type"] == "turn"]
    assert turns and turns[-1]["tool_calls"][-1]["name"] in ("finish", "handoff")
    assert all(t["model"] == demo_script.RESPONSE_MODEL for t in turns)
    # nothing touched the real ledger
    assert not (tmp_path / "spend-ledger.jsonl").exists()
    log = [json.loads(line) for line in (tmp_path / "log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert any(e.get("type") == "turn" for e in log)


@pytest.mark.parametrize("speed", [0])
def test_replay_emits_events_without_timing_fields(tmp_path, speed):
    entry = next(iter(demo.load_index()["runs"].values()))
    out = []
    demo.replay(demo_dir() / entry["dir"], tmp_path, out.append, speed)
    assert out and all("_t" not in e for e in out)
    assert (tmp_path / "report.json").is_file()


def test_scripted_vision_answers_parse():
    """The demo's canned vision answers must keep matching prompts/vision-text.md's format."""
    from printready.vision import parse_answer

    for sample in demo.load_samples():
        answer, problem = parse_answer(demo_script.vision_response(sample.get("vision"))["text"])
        assert answer is not None, (sample["id"], problem)
