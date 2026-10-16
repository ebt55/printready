"""Agent mode (chunk K4): a tool-use loop over the deterministic tools.

Tools: check, look, remove_background, pad_canvas, add_border, bridge_islands, read_text,
regenerate (only with spec.prompt and an image model), finish(outcome, customer_message,
person_notes). Pixels change only through tools. Turn limit 12, then needs_person ("turn limit").
Images go back as a user message after the tool result. Every turn is logged to log.jsonl.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from printready.llm import ChatClient
from printready.profile import Profile
from printready.types import Artwork, Spec

MAX_TURNS = 12


def run_agent(
    art: Artwork,
    spec: Spec,
    profile: Profile,
    client: ChatClient,
    log_path: Path,
    max_turns: int = MAX_TURNS,
) -> dict[str, Any]:
    """Run the agent on one artwork and return the same result shape as pipeline.run_rules."""
    raise NotImplementedError("K4")
