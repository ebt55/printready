"""Model text checks: `text_garbled` and `text_small`.

One call per image: the art cropped to its subject box (768 px long side) plus its printed size.
The model answers JSON only:
    {"text": [{"letters", "seen", "intended", "misspelled", "broken", "box"}], "notes"}
- Reading: `letters` is a letter-by-letter transcription (spelling it out stops the model from
  silently autocorrecting, e.g. WELCME read as WELCOME) and `intended` the correct spelling. Code
  calls a line garbled if their letters differ (ignoring case, spaces and punctuation), if a
  letter could not be made out (`?`), or if the model says a word is misspelled or a glyph broken.
- The model only points; code measures. `box` locates a line of text (fractions of the image);
  code measures its cap height in the full-resolution pixels (glyph heights inside the box), turns
  it into points with Artwork.ppi and compares it with cap_height_ratio x min_text_pt. Vision
  models misjudge small heights badly (dev bench: 2.5 pt text read as 7-12 pt), so no size number
  comes from the model. text_small is OFF by default (PRINTREADY_TEXT_SMALL=1 turns it on): right
  on the bench's flat type, but on real Grok lettering misplaced boxes and stitched or outlined
  letters gave false small-text flags. See docs/vision-notes.md.
A parse failure gets one JSON-only reminder, then both findings are `skip`; an API error (after
the client's own retries) is a `skip` with the error. BudgetExceeded propagates to the caller.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from printready.geometry import bbox
from printready.llm import ChatClient, LLMError, image_part
from printready.profile import PT_PER_IN, Profile
from printready.types import Artwork, Finding, Spec

PROMPT_PATH = Path(__file__).parent / "prompts" / "vision-text.md"
REMINDER = 'Reply with only the JSON object described above, {"text": [...], "notes": "..."}, and no other text.'
TEXT_SMALL_ENV = "PRINTREADY_TEXT_SMALL"  # "0" turns the text_small finding off, "1" on
TEXT_SMALL_DEFAULT = False  # off: false flags on real Grok lettering (docs/vision-notes.md)
BOX_PADS = (0.35, 1.0, 2.0)  # search windows around the model's box, in box heights on every side
MIN_GLYPHS = 2  # a text line has at least this many glyphs
MIN_CONTRAST = 40.0  # RGB distance below which a window counts as one flat colour


def text_small_enabled() -> bool:
    raw = os.environ.get(TEXT_SMALL_ENV)
    return TEXT_SMALL_DEFAULT if raw is None else raw.strip() not in ("0", "false", "off", "")


def check_text(art: Artwork, spec: Spec, profile: Profile, client: ChatClient) -> list[Finding]:
    """The text_garbled finding, and text_small unless it is turned off, for `art` at `spec.size_in`."""
    x0, y0, x1, y1 = subject_box(art)
    w_in, h_in = (x1 - x0) / art.ppi, (y1 - y0) / art.ppi
    scale = (
        f"Order: a {spec.size_in:g} in die-cut sticker. This image is the artwork's outline box; "
        f"it prints {w_in:.2f} in wide and {h_in:.2f} in tall."
    )
    if spec.prompt:
        scale += f" The customer's request was: {json.dumps(spec.prompt)}."
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PROMPT_PATH.read_text(encoding="utf-8")},
        {"role": "user", "content": [{"type": "text", "text": scale}, image_part(art.rgba[y0:y1, x0:x1])]},
    ]
    try:
        resp = client.chat(messages, purpose="vision")
        answer, problem = parse_answer(resp.text)
        if answer is None:  # one retry with a JSON-only reminder
            messages += [
                {"role": "assistant", "content": resp.text or "(no answer)"},
                {"role": "user", "content": REMINDER},
            ]
            resp = client.chat(messages, purpose="vision")
            answer, problem = parse_answer(resp.text)
    except LLMError as exc:
        return skipped("the text check could not reach the model",
                       {"reason": "api error", "error": str(exc), "crop": [x0, y0, x1, y1]})
    # `crop` is the region of art.rgba the model saw (px): its fractional text boxes are relative to it
    trace = {"model": resp.model, "request_sha256": resp.request_sha256, "crop": [x0, y0, x1, y1]}
    if answer is None:
        reason = resp.refusal or problem
        return skipped("the model's answer could not be read", {"reason": "unreadable answer", "error": reason, **trace})
    return findings_from_answer(answer, art, spec, profile, crop=(x0, y0, x1, y1), trace=trace)


def subject_box(art: Artwork) -> tuple[int, int, int, int]:
    """The subject's bounding box, or the whole canvas while there is no subject mask (the same
    basis Artwork.ppi was computed on)."""
    box = bbox(art.subject) if art.subject is not None else None
    return box or (0, 0, art.width, art.height)


def parse_answer(text: str) -> tuple[dict[str, Any] | None, str]:
    """(answer, "") if `text` is the JSON object the prompt asks for, else (None, what is wrong).
    Tolerates a code fence or words around the object; checks every field's type."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        return None, "no JSON object in the answer"
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON ({exc.msg})"
    if not isinstance(data, dict) or not isinstance(data.get("text"), list):
        return None, 'the answer has no "text" list'
    for i, item in enumerate(data["text"]):
        if not isinstance(item, dict) or not isinstance(item.get("seen"), str):
            return None, f'text item {i} has no "seen" string'
        if not isinstance(item.get("broken"), bool):
            return None, f'text item {i} has no true/false "broken"'
        if not isinstance(item.get("misspelled", False), bool) or not isinstance(item.get("letters", ""), str):
            return None, f'text item {i} has a "misspelled" or "letters" of the wrong type'
        box = item.get("box")
        if box is not None and not _valid_box(box):
            return None, f'text item {i} has a "box" that is not [left, top, right, bottom] fractions'
    return data, ""


def _valid_box(box: Any) -> bool:
    if not isinstance(box, list) or len(box) != 4:
        return False
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not -0.01 <= v <= 1.01 for v in box):
        return False
    return box[2] > box[0] and box[3] > box[1]


def _letters(text: str) -> str:
    return re.sub(r"[^0-9A-Z?]", "", text.upper())


# ---------------------------------------------------------------- measuring text height

def cap_height_px(rgb: np.ndarray, box: tuple[float, float, float, float]) -> float | None:
    """Cap height (px) of the line of text the model located at `box` (x0, y0, x1, y1 px of
    `rgb`, HxWx3 on white). None if no line of glyphs is found near it.

    A vision model places boxes around small text only roughly (dev bench: up to one box height
    off), so the search window grows (BOX_PADS x the box height on every side) until it holds a
    whole text line. In each window, ink = pixels far (Otsu on the colour distance) from the
    window's dominant colour; glyphs = 8-connected ink components that do not touch the window
    edge; the line = the largest group of glyphs with similar height on a shared centre line.
    Cap height = the 90th percentile of the line's glyph heights (dots and x-height letters do
    not pull it down; round letters overshoot it by a few percent)."""
    for pad in BOX_PADS:
        line = _main_line(_glyphs(rgb, box, pad), box)
        if len(line) >= MIN_GLYPHS:
            return float(np.percentile([h for _, h in line], 90))
    return None


Glyph = tuple[float, int, int]  # (centre y, height, area) of one ink component, px


def _glyphs(rgb: np.ndarray, box: tuple[float, float, float, float], pad: float) -> list[Glyph]:
    """The ink components inside `box` grown by `pad` box heights."""
    h_img, w_img = rgb.shape[:2]
    x0, y0, x1, y1 = box
    grow = pad * (y1 - y0)
    xa, ya = max(0, int(x0 - grow)), max(0, int(y0 - grow))
    xb, yb = min(w_img, int(np.ceil(x1 + grow))), min(h_img, int(np.ceil(y1 + grow)))
    if xb - xa < 4 or yb - ya < 4:
        return []
    window = rgb[ya:yb, xa:xb].reshape(-1, 3).astype(np.float32)
    distance = np.linalg.norm(window - np.median(window, axis=0), axis=1).reshape(yb - ya, xb - xa)
    if distance.max() < MIN_CONTRAST:  # one flat colour: nothing to read
        return []
    scaled = np.clip(distance * (255.0 / distance.max()), 0, 255).astype(np.uint8)
    otsu, _ = cv2.threshold(scaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = distance > max(otsu * distance.max() / 255.0, MIN_CONTRAST / 2)
    _, _, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    h, w = ink.shape
    return [
        (ya + y + ch / 2, int(ch), int(area)) for x, y, cw, ch, area in stats[1:]
        if x > 0 and y > 0 and x + cw < w and y + ch < h and area >= 4 and ch >= 3
    ]


def _main_line(glyphs: list[Glyph], box: tuple[float, float, float, float]) -> list[tuple[float, int]]:
    """The group of glyphs that share a centre line and have similar heights with the most ink
    (total area): on real art, outlines, shading and texture break into many small specks, and
    counting components would pick them over the letters. Returns (centre y, height) pairs."""
    best: list[Glyph] = []
    for cy, h, _ in glyphs:
        line = [(c, g, a) for c, g, a in glyphs if abs(c - cy) <= 0.6 * max(h, g) and 0.5 <= g / h <= 2.0]
        if sum(a for *_, a in line) > sum(a for *_, a in best):
            best = line
    return [(c, g) for c, g, _ in best]


def _on_white(rgba: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4].astype(np.float32) / 255.0
    return (rgba[..., :3] * a + 255.0 * (1.0 - a)).round().astype(np.uint8)


# ---------------------------------------------------------------- findings

def findings_from_answer(
    answer: dict[str, Any],
    art: Artwork,
    spec: Spec,
    profile: Profile,
    crop: tuple[int, int, int, int],
    trace: dict[str, Any] | None = None,
) -> list[Finding]:
    """Turn a parsed model answer into the findings. Every threshold and measurement is here."""
    trace = trace or {}
    cx0, cy0, cx1, cy1 = crop
    rgb = _on_white(art.rgba)
    items = []
    for item in answer["text"]:
        seen, intended = item["seen"], item.get("intended") or item["seen"]
        letters = item.get("letters") or seen
        cap_px = None
        if item.get("box"):
            bx0, by0, bx1, by1 = item["box"]
            px_box = (cx0 + bx0 * (cx1 - cx0), cy0 + by0 * (cy1 - cy0), cx0 + bx1 * (cx1 - cx0), cy0 + by1 * (cy1 - cy0))
            cap_px = cap_height_px(rgb, px_box)
        items.append({
            "seen": seen,
            "intended": intended,
            "letters": letters,
            "garbled": bool(item.get("misspelled") or item["broken"] or "?" in letters
                            or _letters(letters) != _letters(intended)),
            "misspelled": bool(item.get("misspelled")),
            "broken": item["broken"],
            "box": item.get("box"),
            "cap_height_px": None if cap_px is None else round(cap_px, 1),
            "cap_height_pt": None if cap_px is None else round(cap_px / art.ppi * PT_PER_IN, 2),
        })
    base = {"items": items, "notes": answer.get("notes"), **trace}
    findings = [_garbled_finding(items, base)]
    if text_small_enabled():
        findings.append(_small_finding(items, base, art, spec, profile))
    return findings


def _garbled_finding(items: list[dict[str, Any]], base: dict[str, Any]) -> Finding:
    if not items:
        return Finding("text_garbled", "pass", "No text was found in the art.", base, "none")
    bad = [i for i in items if i["garbled"]]
    if bad:
        shown = ", ".join(f'"{i["seen"]}" (probably "{i["intended"]}")' for i in bad[:3])
        msg = f"The lettering looks garbled: {shown}; a person needs to correct it before printing."
        return Finding("text_garbled", "fail", msg, base, "person")
    shown = ", ".join(f'"{i["seen"]}"' for i in items[:3])
    return Finding("text_garbled", "pass", f"The text reads correctly: {shown}.", base, "none")


def _small_finding(
    items: list[dict[str, Any]], base: dict[str, Any], art: Artwork, spec: Spec, profile: Profile
) -> Finding:
    if not items:
        return Finding("text_small", "pass", "There is no text to measure.", base, "none")
    sized = [i for i in items if i["cap_height_pt"] is not None]
    if not sized:
        measured = {**base, "reason": "no text height could be measured"}
        return Finding("text_small", "skip", "The text height could not be measured.", measured, "none")
    smallest = min(sized, key=lambda i: i["cap_height_pt"])
    cap_pt = smallest["cap_height_pt"]
    threshold = profile.cap_height_ratio * profile.min_text_pt
    border, size = profile.border_in, spec.size_in
    # Text scales with the printable width: at size s' it is cap_pt * (s' - 2b) / (s - 2b).
    needed_in = 2 * border + (size - 2 * border) * threshold / cap_pt
    at_floor_in = art.ppi * (size - 2 * border) / profile.ppi_floor + 2 * border
    text_pt = cap_pt / profile.cap_height_ratio
    measured = {
        **base,
        "min_cap_height_pt": round(cap_pt, 2),
        "min_text_pt_equiv": round(text_pt, 2),
        "threshold_cap_pt": round(threshold, 2),
        "min_size_in_for_text": round(needed_in, 2),
        "max_size_in_at_floor": round(at_floor_in, 2),
        "unmeasured": len(items) - len(sized),
    }
    if cap_pt >= threshold:
        msg = f"The smallest text prints at about {text_pt:.1f} pt at {size:g} in, above the {profile.min_text_pt:g} pt minimum."
        return Finding("text_small", "pass", msg, measured, "none")
    head = (
        f'The smallest text ("{smallest["seen"]}") prints at about {text_pt:.1f} pt at {size:g} in, '
        f"under the {profile.min_text_pt:g} pt minimum"
    )
    if needed_in <= at_floor_in:
        return Finding("text_small", "warn", f"{head}; at {needed_in:.1f} in or larger it is big enough.", measured, "customer")
    msg = f"{head}, and the image is not sharp enough to print larger; a person needs to enlarge the lettering."
    return Finding("text_small", "warn", msg, measured, "person")


def skipped(why: str, measured: dict[str, Any]) -> list[Finding]:
    """The vision findings as `skip` (outcome() then sends the image to a person)."""
    msg = f"The text was not checked: {why}."
    checks = ("text_garbled", "text_small") if text_small_enabled() else ("text_garbled",)
    return [Finding(check, "skip", msg, dict(measured), "none") for check in checks]
