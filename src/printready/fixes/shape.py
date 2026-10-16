"""fit_shape: turn the order into a whole-image rounded-rectangle sticker.

A scene (art with no flat background to cut around) needs a person for a die-cut, but the whole
image makes a good rectangular sticker. No pixel changes. The cut is the canvas inset by bleed_in
with corners of shape_corner_radius_in, and ppi is rescaled so the canvas minus the bleed spans the
ordered size. Besides remove_background this is the only fix that sets ppi, because it changes the
product itself, not the art.
"""

from __future__ import annotations

from printready.fixes._common import copy_with, refuse
from printready.geometry import ppi_for_long_side, rounded_rect_mask
from printready.profile import Profile
from printready.types import Artwork, FixResult, Spec


def fit_shape(art: Artwork, spec: Spec, profile: Profile) -> FixResult:
    """Switch the product to a rounded rectangle of the whole image and build its cut. Refused if
    the art already has a transparent background (it suits a die-cut) or is already a rectangle."""
    if art.shape == "rounded_rect":
        return refuse(art, "The order is already a rounded-rectangle sticker.")
    if art.subject is not None:
        return refuse(art, "The art has a transparent background, so it suits a die-cut sticker.")
    ppi = ppi_for_long_side(max(art.width, art.height), spec, profile, shape="rounded_rect")
    inset_px = round(profile.bleed_in * ppi)
    radius_px = round(profile.shape_corner_radius_in * ppi)
    cut = rounded_rect_mask(art.height, art.width, inset_px, radius_px)
    if not cut.any():
        return refuse(art, "The image is too small for a rounded-rectangle sticker.")
    width_in = art.width / ppi - 2 * profile.bleed_in
    height_in = art.height / ppi - 2 * profile.bleed_in
    measured = {
        "product": "rounded_rect",
        "ppi": round(ppi, 2),
        "finished_w_in": round(width_in, 3),
        "finished_h_in": round(height_in, 3),
        "bleed_in": profile.bleed_in,
        "corner_radius_in": profile.shape_corner_radius_in,
    }
    new = copy_with(art, shape="rounded_rect", ppi=ppi, cut=cut, border_in=None)
    note = f"Changed the order to a rounded-rectangle sticker of the whole image ({width_in:.2f} x {height_in:.2f} in)."
    return FixResult(art=new, ok=True, note=note, measured=measured)
