"""`islands`: the die-cut must be one piece.

Before a border exists: components of the subject dilated by profile.border_in ONLY (no closing),
holes filled. Once a fix has built `art.cut`: components of the cut itself (border art.border_in).
Components holding less subject than speck_max_in2 are specks: dropped and counted. Several
pieces are fixer auto if they join at a dilation of max_bridge_border_in, else person.
"""

from __future__ import annotations

import numpy as np

from printready.checks._common import skip_needs_mask
from printready.geometry import bbox, components, dilate, fill_holes
from printready.profile import Profile
from printready.types import Artwork, Finding, Spec


def check_islands(art: Artwork, spec: Spec, profile: Profile) -> Finding:
    if art.subject is None:
        return skip_needs_mask("islands")
    subject, ppi = art.subject, art.ppi
    speck_px = profile.speck_max_in2 * ppi**2
    if art.cut is not None:
        basis, border = "cut", art.border_in if art.border_in is not None else profile.border_in
        region = art.cut
    else:
        basis, border = "dilate", profile.border_in
        region = fill_holes(dilate(subject, border * ppi))
    found = components(region, speck_px, area_of=subject)
    n = len(found.masks)
    measured = {
        "components": n,
        "specks": found.specks,
        "speck_px": found.speck_px,
        "border_in": border,
        "basis": basis,
        "joins_at_max_bridge": None,
    }
    if n == 1:
        msg = f"The art forms one piece with a {border:g} in border."
        return Finding("islands", "pass", msg, measured, "none")
    if n == 0:
        msg = "Nothing in the image is large enough to cut out, so a person needs to look at it."
        return Finding("islands", "fail", msg, measured, "person")

    kept = subject & np.logical_or.reduce(found.masks)
    joined = components(fill_holes(dilate(kept, profile.max_bridge_border_in * ppi)), speck_px, area_of=kept)
    joins = len(joined.masks) == 1
    measured.update(joins_at_max_bridge=joins, max_pieces=int(profile.max_pieces))
    boxes = [b for m in found.masks if (b := bbox(m & subject)) is not None]
    if n > profile.max_pieces:
        msg = f"The art is in {n} separate pieces, too many to join with one border, so a person needs to decide how to cut it."
        return Finding("islands", "fail", msg, measured, "person", boxes)
    if joins:
        msg = (
            f"The art is in {n} separate pieces; a wider border (up to {profile.max_bridge_border_in:g} in) "
            "can join them into one sticker."
        )
        return Finding("islands", "fail", msg, measured, "auto", boxes)
    msg = f"The art is in {n} separate pieces too far apart for one border to join, so a person needs to decide how to cut it."
    return Finding("islands", "fail", msg, measured, "person", boxes)
