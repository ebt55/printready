"""`product_fit` finding: the order was changed to a whole-image rounded-rectangle sticker.

Reported only after fit_shape (art.shape == "rounded_rect"), as a warn the customer resolves:
accept the rectangle, or ask a person to cut out part of the art instead. It always offers the
person option, because a die-cut of a scene is a design decision, not a mechanical fix.
"""

from __future__ import annotations

from printready.checks._common import rounded
from printready.profile import Profile
from printready.types import Artwork, Finding, Spec


def check_product_fit(art: Artwork, spec: Spec, profile: Profile) -> Finding | None:
    """The product_fit warn for a rounded-rectangle order; None for a die-cut."""
    if art.shape != "rounded_rect":
        return None
    measured = {
        "applies": True,
        "product": art.shape,
        "finished_w_in": rounded(art.width / art.ppi - 2 * profile.bleed_in, 3),
        "finished_h_in": rounded(art.height / art.ppi - 2 * profile.bleed_in, 3),
        "bleed_in": profile.bleed_in,
        "corner_radius_in": profile.shape_corner_radius_in,
    }
    msg = (
        f"This art has no plain background to cut around, so we suggest a {spec.size_in:g} in rounded-rectangle "
        "sticker of the whole image; or ask a person to cut out part of the art."
    )
    return Finding("product_fit", "warn", msg, measured, "customer")
