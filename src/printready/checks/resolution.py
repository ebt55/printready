"""`resolution` check: is the art sharp enough at the ordered size?

Compares Artwork.ppi (subject bounding box over the printable size, set once) with ppi_target
(pass) and ppi_floor (warn between the two, fail below). It always reports the largest sizes that
reach each threshold and how many pixels a min_line_pt line spans. The customer fixes it by
choosing a smaller size, unless even a 1 in sticker would be under the floor (person)."""

from __future__ import annotations

from printready.checks._common import rounded
from printready.geometry import size_margin_in
from printready.profile import Profile
from printready.types import Artwork, Finding, Spec


def check_resolution(art: Artwork, spec: Spec, profile: Profile) -> Finding:
    ppi = art.ppi
    margin = size_margin_in(art.shape, profile)  # border added (die-cut) or bleed trimmed (rectangle)
    long_px = ppi * (spec.size_in - margin)  # the pixel length that set ppi
    at_target = long_px / profile.ppi_target + margin
    at_floor = long_px / profile.ppi_floor + margin
    one_pt_px = profile.pt_to_px(profile.min_line_pt, ppi)
    basis = "image" if art.shape == "rounded_rect" else ("subject" if art.subject is not None else "canvas")
    measured = {
        "ppi": rounded(ppi, 2),
        "basis": basis,
        "max_size_in_at_target": rounded(at_target, 3),
        "max_size_in_at_floor": rounded(at_floor, 3),
        "one_pt_px": rounded(one_pt_px, 2),
    }
    size = f"{spec.size_in:g} in"
    lines = f"lines thinner than {one_pt_px:.1f} px print under {profile.min_line_pt:g} pt"
    where = " (measured on the whole canvas)" if basis == "canvas" else ""
    fixer = "person" if at_floor < 1.0 else "customer"

    if ppi >= profile.ppi_target:
        msg = f"At {size} this art prints at {ppi:.0f} PPI{where}, meeting the {profile.ppi_target:.0f} PPI target; {lines}."
        return Finding("resolution", "pass", msg, measured, "none")
    if ppi >= profile.ppi_floor:
        msg = (
            f"At {size} this art prints at {ppi:.0f} PPI{where}, under the {profile.ppi_target:.0f} PPI target; "
            f"it is sharp at {at_target:.1f} in or smaller."
        )
        return Finding("resolution", "warn", msg, measured, fixer)
    if fixer == "person":
        msg = (
            f"At {size} this art prints at only {ppi:.0f} PPI{where}, and even a 1 in sticker would look soft; "
            "it needs a larger image."
        )
    else:
        msg = (
            f"At {size} this art prints at only {ppi:.0f} PPI{where} and will look soft; "
            f"it stays above {profile.ppi_floor:.0f} PPI up to {at_floor:.1f} in."
        )
    return Finding("resolution", "fail", msg, measured, fixer)
