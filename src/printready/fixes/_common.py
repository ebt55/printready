"""Helpers shared by the fix modules."""

from __future__ import annotations

from typing import Any

from printready.types import Artwork, FixResult


def refuse(art: Artwork, note: str, **measured: Any) -> FixResult:
    """ok=False with the input art unchanged (a copy, so callers never share arrays)."""
    return FixResult(art=art.copy(), ok=False, note=note, measured=measured)


def evolve(art: Artwork, **changes: Any) -> Artwork:
    """A new Artwork with `changes`, deep-copying everything else (history and meta included)."""
    base = art.copy()
    for key, value in changes.items():
        setattr(base, key, value)
    base.__post_init__()  # re-validate shapes after the change
    return base
