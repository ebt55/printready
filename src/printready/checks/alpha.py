"""`soft_alpha` check: is there a wide semi-transparent band (shadow, glow) around the art?

The statistic is the 95th percentile distance, in inches, from each partial-alpha pixel (16-239)
to the nearest opaque art pixel (240+). Above soft_alpha_max_in it warns for a person: nobody can
say where the cut belongs. It reads the art layer only (geometry.art_alpha), so the white border a
fix paints can never hide a shadow."""

from __future__ import annotations

import math

from printready.checks._common import not_applicable, rounded, skip_needs_mask
from printready.geometry import PARTIAL_ALPHA, art_alpha, bbox, soft_alpha_p95_px
from printready.profile import Profile
from printready.types import Artwork, Finding, Spec


def check_soft_alpha(art: Artwork, spec: Spec, profile: Profile) -> Finding:
    if art.shape == "rounded_rect":
        return not_applicable("soft_alpha")
    if art.subject is None:
        return skip_needs_mask("soft_alpha")
    alpha = art_alpha(art.rgba, art.subject)  # never the border or padding a fix added
    lo, hi = PARTIAL_ALPHA
    partial = (alpha >= lo) & (alpha <= hi)
    p95_px = soft_alpha_p95_px(alpha)
    band_in = p95_px / art.ppi
    measured = {
        "band_p95_in": None if math.isinf(band_in) else rounded(band_in),
        "limit_in": profile.soft_alpha_max_in,
        "partial_px": int(partial.sum()),
    }
    if band_in <= profile.soft_alpha_max_in:
        return Finding("soft_alpha", "pass", "The art's edges are crisp enough to place the cut line.", measured, "none")
    box = bbox(partial)
    if math.isinf(band_in):
        msg = "No part of the art is fully opaque, so a person needs to decide where the cut goes."
    else:
        msg = (
            f"The art has a soft semi-transparent edge (shadow or glow) about {band_in:.2f} in wide, "
            "so a person needs to decide where the cut goes."
        )
    return Finding("soft_alpha", "warn", msg, measured, "person", boxes=[box] if box else [])
