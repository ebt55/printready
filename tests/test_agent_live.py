"""Live smoke test against xAI: one vision call and one short agent run on the badge fixture.

Skipped unless PRINTREADY_LIVE=1. Uses XAI_API_KEY from the environment or the repo .env, and
every call goes through the spend guard and the real ledger (results/spend-ledger.jsonl).
Expected cost: well under $0.10. Run:  PRINTREADY_LIVE=1 uv run pytest tests/test_agent_live.py -s
"""

import json
import os
from pathlib import Path

import pytest

from printready import spend
from printready.agent import LOG_NAME, TOOLS, run_agent
from printready.imageio import load_artwork
from printready.llm import image_part, make_client
from printready.profile import load_profile
from printready.render import render_proof
from printready.types import Spec, outcome
from printready.vision import check_text

pytestmark = pytest.mark.skipif(os.environ.get("PRINTREADY_LIVE") != "1", reason="live xAI calls: set PRINTREADY_LIVE=1")

MODEL = os.environ.get("PRINTREADY_LIVE_MODEL", "xai:grok-4.3")
FIXTURE = Path(__file__).parent / "fixtures" / "badge-on-white.jpg"
P = load_profile()
SPEC = Spec("die_cut", 3.0)


def test_live_vision_text_check():
    client = make_client(MODEL)
    findings = check_text(load_artwork(FIXTURE, SPEC, P), SPEC, P, client)
    print(f"\nvision: {[(f.check, f.status) for f in findings]} model={findings[0].measured.get('model')} "
          f"cost=${client.cost_usd:.5f} ledger=${spend.ledger_total():.4f}")
    assert [f.check for f in findings] == ["text_garbled", "text_small"]
    assert all(f.status != "skip" for f in findings), findings[0].measured  # wire format works, answer parsed
    assert findings[0].status == "pass"  # the badge has no letters


def test_live_image_after_tool_result_shape():
    """One call in exactly the shape the agent sends after `look`: assistant tool call, tool
    result, then the image in a user message. (The short agent run may not call look.)"""
    client = make_client(MODEL)
    proof = render_proof(load_artwork(FIXTURE, SPEC, P), SPEC, P)
    messages = [
        {"role": "system", "content": "You check sticker proofs. Answer in one short sentence."},
        {"role": "user", "content": "Look at the proof and say what shape the sticker is."},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "call_look_1", "type": "function", "function": {"name": "look", "arguments": '{"view": "proof"}'}}]},
        {"role": "tool", "tool_call_id": "call_look_1", "content": '{"ok": true, "file": "look-1-proof.png"}'},
        {"role": "user", "content": [{"type": "text", "text": "Image from look (call call_look_1): look-1-proof.png"},
                                     image_part(proof)]},
    ]
    resp = client.chat(messages, tools=TOOLS, purpose="smoke")
    print(f"\nimage-after-tool: {resp.text!r} tool_calls={[c.name for c in resp.tool_calls]} model={resp.model} "
          f"tokens={resp.tokens_in}/{resp.tokens_out} ${resp.cost_usd:.5f}")
    assert resp.text or resp.tool_calls


def test_live_agent_short_run(tmp_path):
    client = make_client(MODEL)
    result = run_agent(FIXTURE, SPEC, P, tmp_path, client, max_turns=3)
    lines = [json.loads(x) for x in (tmp_path / LOG_NAME).read_text(encoding="utf-8").splitlines()]
    turns = [x for x in lines if x["type"] == "turn"]
    for t in turns:
        print(f"\nturn {t['n']}: {[(c['name'], c['result']) for c in t['tool_calls']]} tokens={t['tokens']} "
              f"${t['cost_usd']:.5f} {t['latency_ms']} ms model={t.get('model')}")
    print(f"outcome={result.outcome} handoff={result.handoff_reason} cost=${result.cost_usd:.5f} "
          f"ledger=${spend.ledger_total():.4f}\nmessage: {result.customer_message}")
    assert result.handoff_reason not in ("error", "budget"), result.person_notes
    assert turns and all(t.get("model") for t in turns)
    assert any(c["name"] in ("remove_background", "check", "look") for t in turns for c in t["tool_calls"])
    assert result.outcome == outcome(result.art, result.after, handoff=result.handoff_reason is not None)
