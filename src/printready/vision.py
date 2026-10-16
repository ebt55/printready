"""Model text checks (chunk K4): text_garbled and text_small.

One call per image with the image and the physical scale; JSON-only answer. Code converts each
cap_height_frac to points with px_per_in and compares it with 0.7 x min_text_pt. The prompt lives
in prompts/vision-text.md. A parse failure gets one retry, then a `skip` finding with the reason.
"""

from __future__ import annotations

from printready.llm import ChatClient
from printready.profile import Profile
from printready.types import Artwork, Finding, Spec


def read_text(art: Artwork, spec: Spec, profile: Profile, client: ChatClient) -> list[Finding]:
    """Return the text_garbled and text_small findings for `art` at `spec.size_in`."""
    raise NotImplementedError("K4")
