"""The scripted "model" behind demo runs: real tools, a scripted conversation.

Demo runs are produced by the REAL pipeline.run_rules and agent.run_agent. Only the model is
scripted, through llm's fake provider: a list of responses (text, tool calls, token usage) written
here from what the real checks found on that image. Tool results, findings, fixes, guard results,
proofs and outcomes are all real; token counts are scripted, cost is computed from them at
grok-4.3 list prices, and latency is measured (the transport waits a scripted time per reply).
The UI labels these runs "scripted demo model". Nothing touches the real spend ledger.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DEMO_MODEL_ID = "fake:demo-script"
RESPONSE_MODEL = "demo-script"  # what the "API" reports as its model id; shown in the trace
PRICE = (1.25, 0.20, 2.50)  # grok-4.3 list prices per 1M tokens: input, cached input, output


def make_client(responses: list[dict[str, Any]], ledger: Path, speed: float = 1.0):
    """A ChatClient over a fake transport that waits each response's `delay_ms` (times `speed`)."""
    from printready.llm import ChatClient, FakeTransport
    from printready.spend import Price

    class PacedFakeTransport(FakeTransport):
        def post(self, path: str, payload: bytes):
            if self.responses:
                delay = self.responses[0].pop("delay_ms", 0)
                if delay and speed > 0:
                    time.sleep(delay / 1000.0 * speed)
            return super().post(path, payload)

    price = Price(in_per_m=PRICE[0], cached_per_m=PRICE[1], out_per_m=PRICE[2])
    return ChatClient(DEMO_MODEL_ID, PacedFakeTransport([dict(r) for r in responses]), price=price, ledger=ledger)


def vision_response(vision: dict | None) -> dict[str, Any]:
    """The vision check's JSON answer, in the shape prompts/vision-text.md asks for."""
    vision = vision or {"text": [], "notes": "No lettering in the art."}
    answer = {"text": vision.get("text", []), "notes": vision.get("notes", "")}
    out = 40 + len(json.dumps(answer)) // 4
    return {"text": json.dumps(answer), "usage": {"in": 1460, "cached": 0, "out": out},
            "delay_ms": 1300 + out * 6, "model": RESPONSE_MODEL}


# ------------------------------------------------------------------ the agent conversation

class _Script:
    """Builds the response list turn by turn with plausible, deterministic token counts."""

    def __init__(self) -> None:
        self.responses: list[dict[str, Any]] = []
        self.prompt = 2350  # system prompt + order + check report + the uploaded image
        self.images_pending = 0

    def turn(self, text: str, tool: str, args: dict | None = None) -> None:
        args = args or {}
        n = sum(1 for r in self.responses if r.get("tool_calls"))
        tokens_in = self.prompt + 1100 * self.images_pending
        cached = 0 if n == 0 else int(self.prompt * 0.92)
        out = 18 + len(text) // 4 + len(json.dumps(args)) // 4 + 12
        self.responses.append({
            "text": text, "tool_calls": [{"name": tool, "arguments": args}],
            "usage": {"in": tokens_in, "cached": cached, "out": out},
            "delay_ms": 650 + out * 11 + 700 * self.images_pending, "model": RESPONSE_MODEL,
        })
        self.prompt = tokens_in + out + 160  # the tool result joins the conversation
        self.images_pending = 1 if tool == "look" else 0

    def vision(self, vision: dict | None) -> None:
        self.responses.append(vision_response(vision))


def _agent_tools() -> tuple[str, ...]:
    try:
        from printready.agent import TOOL_NAMES

        return tuple(TOOL_NAMES)
    except Exception:
        return ()


def _by_check(report: dict) -> dict[str, dict]:
    return {f["check"]: f for f in report.get("findings", [])}


def _size(spec_size: float) -> str:
    return f"{spec_size:g} in"


def agent_responses(rules: dict, size_in: float, vision: dict | None = None, look_note: str | None = None,
                    handoff: str | None = None, handoff_note: str | None = None) -> list[dict[str, Any]]:
    """A sensible tool sequence for this image, decided from a rules-mode run on the same file.

    `rules` is that run's RunResult dict; `vision` is the canned answer for read_text (None: no
    lettering, so the agent does not call it); `handoff` forces a handoff after looking (used to
    give the demo real set a few honest disagreements between the modes).
    """
    s = _Script()
    size = _size(size_in)
    before, after = _by_check(rules["before"]), _by_check(rules["after"])
    applied = [h["fix"] for h in rules.get("history", []) if h.get("ok")]
    bg = before.get("background", {})
    res = after.get("resolution", before.get("resolution", {}))
    ppi = (res.get("measured") or {}).get("ppi")
    has_text = bool(vision and vision.get("text"))

    if bg.get("status") == "fail" and bg.get("fixer") == "person":
        if "fit_shape" in _agent_tools():
            s.turn("There is no flat background: this is a scene that fills the canvas, so there is no edge to cut "
                   "around. It fits a whole-image rounded-rectangle sticker better than a die-cut.", "fit_shape")
            s.turn("Let me look at the rounded-rectangle proof.", "look", {"view": "proof"})
            msg = ("Your art is a full scene, so we suggest printing the whole image as a rounded-rectangle sticker; "
                   "the magenta line shows the cut. Prefer a die-cut? Ask us and a person will cut out part of it. "
                   "Approve the proof if it looks right.")
            s.turn("The corners are even and the whole scene sits inside the bleed. Writing the message, with the "
                   "person option, and finishing.", "finish", {"customer_message": msg})
            return s.responses
        s.turn("The background is not one solid colour, so removing it would mean guessing where the art ends. "
               "That is a person's call, not a tool's.", "handoff",
               {"reason": "background is not one colour",
                "person_notes": "Gradient or textured background: cut the subject out by hand."})
        return s.responses

    if bg.get("status") == "fail" and bg.get("fixer") == "auto":
        hexcol = (bg.get("measured") or {}).get("colour_hex", "solid")
        s.turn(f"The report shows a solid {hexcol} background (fixer auto) and three checks waiting on a subject "
               "mask. A one-colour edge ring is safe to flood-fill away, so I'll start there.", "remove_background")
        s.turn("Background removed and the damage guard passed. Re-running the checks now that the subject mask "
               "exists.", "check")

    edge = after.get("edge_crop", {})
    if edge.get("status") == "fail":
        m = edge.get("measured") or {}
        where = m.get("edge") or "canvas"
        run = m.get("longest_run_in")
        length = f" for {run:.2f} in" if isinstance(run, (int, float)) else ""
        s.turn(f"The art runs off the {where} edge{length}, so part of the drawing is missing. Padding the canvas "
               "would only frame the crop; the customer needs to send the full artwork. Handing off.", "handoff",
               {"reason": "art cut off at the edge",
                "person_notes": f"The subject is cropped at the {where} edge{length}. Ask for the uncropped file."})
        return s.responses

    if "pad_canvas" in applied:
        s.turn("The art sits too close to the canvas edge for the border to fit. Adding transparent space first.",
               "pad_canvas")

    border = "Adding the standard 0.1 in white border and building the cut line."
    if res.get("status") in ("warn", "fail") and isinstance(ppi, (int, float)):
        text = (f"At {size} this prints at {ppi:.0f} PPI, under the 300 PPI target. A smaller size is the "
                f"customer's call, so it goes in the message. The art itself is clean. {border}")
    elif isinstance(ppi, (int, float)):
        text = f"Resolution is fine at {ppi:.0f} PPI for {size}. {border}"
    else:
        text = border
    s.turn(text, "add_border")

    if "bridge_islands" in applied:
        n = (before.get("islands", {}).get("measured") or {}).get("components") or 2
        s.turn(f"The cut is still {n} separate outlines. The parts are close enough for a wider border (up to "
               "0.25 in) to join them, so I'll bridge them into one sticker.", "bridge_islands")

    s.turn("Before deciding, let me look at the proof the customer would see.", "look", {"view": "proof"})
    seen = look_note or "The cut line follows the outline at an even distance, and nothing is clipped."

    if has_text:
        s.turn(f"{seen} There is lettering in the art, and spelling is something only a vision check can judge, "
               "so I'll read it.", "read_text")
        s.vision(vision)
        garbled = [t for t in vision["text"] if t.get("misspelled") or t.get("broken") or t.get("garbled")]
        if garbled:
            words = ", ".join(f"{t['seen']} (probably {t['intended']})" for t in garbled)
            s.turn(f"The text check reads {words}. My tools cannot redraw lettering, so this goes to a person. "
                   "The border and cut line are ready for them.", "handoff",
                   {"reason": "garbled text",
                    "person_notes": f"Lettering reads {' '.join(t['seen'] for t in garbled)}; probably "
                                    f"{' '.join(t['intended'] for t in garbled)}. Correct or regenerate the words."})
            return s.responses
        seen = "The lettering reads correctly."

    person = [f for f in after.values() if f.get("status") in ("warn", "fail") and f.get("fixer") in ("person", "none")]
    if handoff or person:
        reason = handoff or {"soft_alpha": "soft glow or shadow edge", "islands": "parts too far apart",
                             "resolution": "too few pixels at any size"}.get(person[0]["check"], person[0]["check"])
        note = handoff_note or (person[0]["message"] if person else reason)
        s.turn(f"{seen} {('But ' + reason + ' is') if handoff else 'This is'} a design decision my tools should "
               "not make. Handing off with notes.", "handoff", {"reason": reason, "person_notes": note})
        return s.responses

    did = []
    if "remove_background" in applied:
        did.append("removed the background")
    did.append("joined the parts with a slightly wider white border" if "bridge_islands" in applied
               else "added a 0.1 in white border")
    msg = f"Hi! We {' and '.join(did)}; the magenta line shows where your sticker will be cut."
    m = res.get("measured") or {}
    if res.get("status") in ("warn", "fail") and m.get("max_size_in_at_target"):
        msg += (f" At {size} it prints at {m['ppi']:.0f} PPI and may look soft; it stays sharp up to "
                f"{m['max_size_in_at_target']:.1f} in, so a smaller size would print crisper.")
    msg += " Approve the proof if it looks right."
    s.turn(f"{seen} The proof is ready to send, so I'll write the customer message and finish.", "finish",
           {"customer_message": msg})
    return s.responses
