"""`resolution`: Artwork.ppi against ppi_target / ppi_floor, with the largest sharp sizes."""

from __future__ import annotations

from printready.checks._common import r
from printready.profile import Profile
from printready.types import Artwork, Finding, Spec


def check_resolution(art: Artwork, spec: Spec, profile: Profile) -> Finding:
    ppi = art.ppi
    border = profile.border_in
    long_px = ppi * (spec.size_in - 2 * border)  # the bbox long side that set ppi
    at_target = long_px / profile.ppi_target + 2 * border
    at_floor = long_px / profile.ppi_floor + 2 * border
    one_pt_px = profile.pt_to_px(profile.min_line_pt, ppi)
    basis = "subject" if art.subject is not None else "canvas"
    measured = {
        "ppi": r(ppi, 2),
        "basis": basis,
        "max_size_in_at_target": r(at_target, 3),
        "max_size_in_at_floor": r(at_floor, 3),
        "one_pt_px": r(one_pt_px, 2),
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
