"""Model text checks: `text_garbled` and `text_small` (the two things pixels cannot settle).

One call per image: the art cropped to its subject box (768 px long side) plus its printed size.
The model answers JSON only, {"text": [{"seen", "intended", "garbled", "cap_height_frac"}], "notes"};
`cap_height_frac` is cap height over the crop height, so code converts it to points with
Artwork.ppi and compares it with cap_height_ratio x min_text_pt. The model never sees a threshold.
A parse failure gets one JSON-only reminder, then both findings are `skip`; an API error (after
the client's own retries) is a `skip` with the error. BudgetExceeded propagates to the caller.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from printready.geometry import bbox
from printready.llm import ChatClient, LLMError, image_part
from printready.profile import PT_PER_IN, Profile
from printready.types import Artwork, Finding, Spec

PROMPT_PATH = Path(__file__).parent / "prompts" / "vision-text.md"
REMINDER = 'Reply with only the JSON object described above, {"text": [...], "notes": "..."}, and no other text.'


def check_text(art: Artwork, spec: Spec, profile: Profile, client: ChatClient) -> list[Finding]:
    """The text_garbled and text_small findings for `art` at `spec.size_in` (always both)."""
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
        return skipped("the text check could not reach the model", {"reason": "api error", "error": str(exc)})
    trace = {"model": resp.model, "request_sha256": resp.request_sha256}
    if answer is None:
        reason = resp.refusal or problem
        return skipped("the model's answer could not be read", {"reason": "unreadable answer", "error": reason, **trace})
    return findings_from_answer(answer, art, spec, profile, crop_height_px=y1 - y0, trace=trace)


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
        if not isinstance(item.get("garbled"), bool):
            return None, f'text item {i} has no true/false "garbled"'
        frac = item.get("cap_height_frac")
        if frac is not None and (isinstance(frac, bool) or not isinstance(frac, (int, float)) or not 0 < frac <= 1):
            return None, f'text item {i} has a "cap_height_frac" outside 0..1'
    return data, ""


def findings_from_answer(
    answer: dict[str, Any],
    art: Artwork,
    spec: Spec,
    profile: Profile,
    crop_height_px: int,
    trace: dict[str, Any] | None = None,
) -> list[Finding]:
    """Turn a parsed model answer into the two findings. All thresholds are applied here."""
    trace = trace or {}
    notes = answer.get("notes")
    items = []
    for item in answer["text"]:
        frac = item.get("cap_height_frac")
        cap_pt = None if frac is None else frac * crop_height_px / art.ppi * PT_PER_IN
        items.append({
            "seen": item["seen"],
            "intended": item.get("intended") or item["seen"],
            "garbled": item["garbled"],
            "cap_height_frac": frac,
            "cap_height_pt": None if cap_pt is None else round(cap_pt, 2),
        })
    base = {"items": items, "notes": notes, **trace}
    return [_garbled_finding(items, base), _small_finding(items, base, art, spec, profile)]


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
        measured = {**base, "reason": "no text height in the answer"}
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
    """Both vision findings as `skip` (outcome() then sends the image to a person)."""
    msg = f"The text was not checked: {why}."
    return [Finding("text_garbled", "skip", msg, measured, "none"), Finding("text_small", "skip", msg, dict(measured), "none")]
