"""Damage guard (chunk K3): runs after every fix, in both modes, and is part of the score.

- add_border, bridge_islands, pad_canvas: every subject pixel must stay bit-identical
  (after accounting for the padding offset).
- remove_background: damage = area(removed pixels more than DAMAGE_DELTA_E from the background
  colour) / area(kept subject); above MAX_DAMAGE_FRAC is damaged.
A damaged fix is reverted, recorded in history, and the image's outcome becomes needs_person.
"""

from __future__ import annotations

from typing import Any, Callable

from printready.profile import Profile
from printready.types import Artwork, FixResult, Spec

MAX_DAMAGE_FRAC = 0.02


def damage(fix_name: str, before: Artwork, after: Artwork) -> tuple[bool, dict[str, Any]]:
    """Return (damaged, measured) for one applied fix, comparing `before` with `after`."""
    raise NotImplementedError("K3")


def apply_guarded(
    fix: Callable[..., FixResult], art: Artwork, spec: Spec, profile: Profile, **kwargs: Any
) -> tuple[FixResult, bool]:
    """Run `fix`, then the guard. Returns (result, damaged); a damaged result carries the original art."""
    raise NotImplementedError("K3")
