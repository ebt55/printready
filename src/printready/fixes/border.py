"""add_border and bridge_islands: build the die-cut mask and paint the white border.

Only pixels inside the cut with alpha below 16 (fully transparent) become white; every subject
pixel and every partial-alpha pixel (anti-aliased edge, shadow) is left as it is, so the guard's
bit-identical rule holds and a soft shadow stays visible to the soft_alpha check.
"""

from __future__ import annotations

import numpy as np

from printready.fixes._common import evolve, refuse
from printready.geometry import (
    PARTIAL_ALPHA,
    components,
    cut_mask,
    dilate,
    edge_pixel_count,
    fill_holes,
)
from printready.profile import Profile
from printready.types import Artwork, FixResult, Spec

WHITE = np.array([255, 255, 255, 255], np.uint8)
BRIDGE_TOLERANCE_IN = 0.005  # bisection stops when the border is known to this precision


def _cut(art: Artwork, profile: Profile, border_in: float) -> np.ndarray:
    return cut_mask(art.subject, art.ppi, border_in, profile.min_neck_in, profile.speck_max_in2)


def _pieces(mask: np.ndarray, art: Artwork, profile: Profile) -> int:
    return len(components(mask, profile.speck_max_in2 * art.ppi**2, area_of=art.subject).masks)


def _with_border(art: Artwork, cut: np.ndarray, border_in: float) -> Artwork:
    rgba = art.rgba.copy()
    rgba[cut & (rgba[..., 3] < PARTIAL_ALPHA[0])] = WHITE
    return evolve(art, rgba=rgba, cut=cut, border_in=float(border_in))


def add_border(art: Artwork, spec: Spec, profile: Profile, border_in: float | None = None) -> FixResult:
    """White border of `border_in` (default profile.border_in), closing of diameter min_neck_in,
    smooth outline; builds art.cut."""
    if art.subject is None:
        return refuse(art, "A border needs the background removed first.")
    border = profile.border_in if border_in is None else float(border_in)
    if border < profile.border_min_in:
        return refuse(art, f"A {border:g} in border is below the {profile.border_min_in:g} in minimum.")
    cut = _cut(art, profile, border)
    clipped = edge_pixel_count(cut) > 0
    measured = {"border_in": border, "pieces": _pieces(cut, art, profile), "clipped_at_edge": clipped}
    note = f"Added a {border:g} in white border and built the cut line."
    if clipped:
        note += " The border runs off the image edge."
    return FixResult(art=_with_border(art, cut, border), ok=True, note=note, measured=measured)


def bridge_islands(art: Artwork, spec: Spec, profile: Profile) -> FixResult:
    """Grow the border (up to max_bridge_border_in) to the smallest width that makes the cut one
    piece. Refused if the art is already one piece at the standard border (dilate-only, as the
    islands check judges it) or if the pieces do not join even at the maximum."""
    if art.subject is None:
        return refuse(art, "Joining pieces needs the background removed first.")
    ppi = art.ppi
    standard = fill_holes(dilate(art.subject, profile.border_in * ppi))
    n_start = _pieces(standard, art, profile)
    if n_start <= 1:
        return refuse(art, "The art is already one piece; no bridge needed.", pieces=n_start)

    lo = max(profile.border_in, art.border_in or 0.0)
    hi = profile.max_bridge_border_in
    cut = _cut(art, profile, lo)
    if _pieces(cut, art, profile) == 1:
        border = lo  # the border closing already joins them
    else:
        cut = _cut(art, profile, hi)
        n_max = _pieces(cut, art, profile)
        if n_max > 1:
            return refuse(
                art,
                f"The {n_start} pieces stay apart even with a {hi:g} in border, so a person needs to decide how to cut them.",
                pieces=n_max,
            )
        while hi - lo > BRIDGE_TOLERANCE_IN:
            mid = (lo + hi) / 2
            trial = _cut(art, profile, mid)
            if _pieces(trial, art, profile) == 1:
                hi, cut = mid, trial
            else:
                lo = mid
        border = hi
    measured = {"border_in": round(border, 4), "pieces_before": n_start, "clipped_at_edge": edge_pixel_count(cut) > 0}
    note = f"Joined {n_start} pieces into one sticker with a {border:.2f} in border."
    return FixResult(art=_with_border(art, cut, border), ok=True, note=note, measured=measured)
