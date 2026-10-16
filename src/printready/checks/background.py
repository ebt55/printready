"""`background` check: does the art still sit on a background?

Art with real transparency passes. An opaque image fails: when at least bg_ring_uniform_frac of
its outer 2 % ring is within bg_delta_e (CIEDE2000) of one colour, remove_background can take it
off (auto); gradients, textures and photos need a person."""

from __future__ import annotations

from printready.checks._common import not_applicable, rounded
from printready.geometry import ring_uniformity
from printready.profile import Profile
from printready.types import Artwork, Finding, Spec


def check_background(art: Artwork, spec: Spec, profile: Profile) -> Finding:
    if art.shape == "rounded_rect":
        return not_applicable("background")
    if art.subject is not None:
        removed = any(s.fix == "remove_background" and s.ok for s in art.history)
        msg = "The background was removed." if removed else "The background is transparent."
        return Finding("background", "pass", msg, {"real_alpha": True, "removed": removed}, "none")
    ring = ring_uniformity(art.rgba[..., :3], profile.bg_delta_e)
    colour = "#{:02x}{:02x}{:02x}".format(*ring.rgb)
    measured = {
        "real_alpha": False,
        "colour_rgb": list(ring.rgb),
        "colour_hex": colour,
        "colour_lab": [rounded(v, 2) for v in ring.lab],
        "ring_uniform_frac": rounded(ring.uniform_frac),
        "ring_band_px": ring.band_px,
    }
    if ring.uniform_frac >= profile.bg_ring_uniform_frac:
        msg = f"The art sits on a solid {colour} background, which we can remove so the sticker is cut to the art's shape."
        return Finding("background", "fail", msg, measured, "auto")
    msg = "The art sits on a background that is not one colour (gradient, texture or photo), so a person needs to cut it out."
    return Finding("background", "fail", msg, measured, "person")
