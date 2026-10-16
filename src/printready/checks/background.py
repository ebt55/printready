"""`background`: an opaque image needs its background removed; a one-colour ring can be
removed automatically, anything else (gradient, texture, photo) goes to a person."""

from __future__ import annotations

from printready.checks._common import r
from printready.geometry import ring_uniformity
from printready.profile import Profile
from printready.types import Artwork, Finding, Spec


def check_background(art: Artwork, spec: Spec, profile: Profile) -> Finding:
    if art.subject is not None:
        return Finding("background", "pass", "The background is already transparent.", {"real_alpha": True}, "none")
    ring = ring_uniformity(art.rgba[..., :3], profile.bg_delta_e)
    colour = "#{:02x}{:02x}{:02x}".format(*ring.rgb)
    measured = {
        "real_alpha": False,
        "colour_rgb": list(ring.rgb),
        "colour_hex": colour,
        "colour_lab": [r(v, 2) for v in ring.lab],
        "ring_uniform_frac": r(ring.uniform_frac),
        "ring_band_px": ring.band_px,
    }
    if ring.uniform_frac >= profile.bg_ring_uniform_frac:
        msg = f"The art sits on a solid {colour} background, which we can remove so the sticker is cut to the art's shape."
        return Finding("background", "fail", msg, measured, "auto")
    msg = "The art sits on a background that is not one colour (gradient, texture or photo), so a person needs to cut it out."
    return Finding("background", "fail", msg, measured, "person")
