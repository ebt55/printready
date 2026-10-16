"""Deterministic fixes (chunk K3). One module per fix lives in this package.

Every fix is pure: it returns a FixResult with a new Artwork and never changes its input.
The damage guard (guard.py) runs after each one.
"""

from __future__ import annotations

from printready.profile import Profile
from printready.types import Artwork, FixResult, Spec


def remove_background(
    art: Artwork, spec: Spec, profile: Profile, tolerance: float | None = None
) -> FixResult:
    """Remove a solid (uniform-ring) background.

    Flood fill from the canvas edge in a perceptual colour space within `tolerance`, keep the
    subject, 1 px feather, unblend the background colour from edge pixels. ok=False if it would
    remove more than 95 % or less than 2 % of the canvas, or the subject touches more than one edge.
    """
    raise NotImplementedError("K3")


def add_border(art: Artwork, spec: Spec, profile: Profile, border_in: float | None = None) -> FixResult:
    """Add a white border of `border_in` (default profile.border_in) and build `art.cut`.

    Closes waists with a morphological closing of diameter min_neck_in and smooths the outline.
    Subject pixels are never altered.
    """
    raise NotImplementedError("K3")


def bridge_islands(art: Artwork, spec: Spec, profile: Profile) -> FixResult:
    """Grow the border, up to max_bridge_border_in, until the cut mask is one component; else ok=False."""
    raise NotImplementedError("K3")


def pad_canvas(art: Artwork, spec: Spec, profile: Profile) -> FixResult:
    """Add a transparent margin so the border fits inside the canvas. Subject pixels unchanged."""
    raise NotImplementedError("K3")


def recommend_size(art: Artwork, spec: Spec, profile: Profile) -> dict:
    """Largest sizes that meet the PPI rules: {"max_size_in_at_target": .., "max_size_in_at_floor": ..}."""
    raise NotImplementedError("K3")
