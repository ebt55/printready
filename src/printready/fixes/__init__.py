"""Deterministic fixes, one module per fix. Each is pure: it returns a FixResult with a new
Artwork and never changes its input, and it does not touch `history` (guard.apply_fix records
the Step). Call them through `guard.apply_fix` so the damage guard runs."""

from __future__ import annotations

from printready.fixes.background import remove_background
from printready.fixes.border import add_border, bridge_islands
from printready.fixes.pad import pad_canvas
from printready.fixes.shape import fit_shape
from printready.geometry import size_margin_in
from printready.profile import Profile
from printready.types import Artwork, Spec


def recommend_size(art: Artwork, spec: Spec, profile: Profile) -> dict:
    """Largest finished sizes of this product that meet the PPI rules at this art's pixel size."""
    margin = size_margin_in(art.shape, profile)
    long_px = art.ppi * (spec.size_in - margin)
    return {
        "max_size_in_at_target": round(long_px / profile.ppi_target + margin, 3),
        "max_size_in_at_floor": round(long_px / profile.ppi_floor + margin, 3),
        "ppi_at_size": round(art.ppi, 2),
    }


__all__ = ["add_border", "bridge_islands", "fit_shape", "pad_canvas", "recommend_size", "remove_background"]
