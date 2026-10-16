"""Cut line as SVG, in inches, magenta 0.5 pt stroke.

The SVG covers the whole canvas at Artwork.ppi (width = canvas px / ppi inches), so it lines up
with fixed.png at the same physical size. A die-cut traces the outline of `art.cut`; a whole-image
sticker is an exact rounded rectangle inset by the bleed.
"""

from __future__ import annotations

from printready.geometry import outline_polygons
from printready.profile import PT_PER_IN, Profile
from printready.types import SHAPE_LABELS, Artwork, Spec

CUT_COLOUR = "#ff00ff"
CUT_STROKE_PT = 0.5


def cutline_svg(art: Artwork, spec: Spec, profile: Profile) -> str:
    """Closed path(s), one per piece of the cut, simplified, coordinates in inches; or one rounded
    <rect> for a whole-image sticker."""
    if art.cut is None:
        raise ValueError("art.cut is None: build the cut mask (add_border) before drawing the cut line")
    ppi = art.ppi
    w_in, h_in = art.width / ppi, art.height / ppi
    stroke = f'fill="none" stroke="{CUT_COLOUR}" stroke-width="{CUT_STROKE_PT / PT_PER_IN:.5f}"'
    paths = []
    if art.shape == "rounded_rect":
        bleed, radius = profile.bleed_in, profile.shape_corner_radius_in
        paths.append(
            f'  <rect x="{bleed:.4f}" y="{bleed:.4f}" width="{w_in - 2 * bleed:.4f}" height="{h_in - 2 * bleed:.4f}" '
            f'rx="{radius:.4f}" ry="{radius:.4f}" {stroke}/>'
        )
    for poly in outline_polygons(art.cut, ppi) if art.shape == "die_cut" else []:
        points = " L ".join(f"{x / ppi:.4f} {y / ppi:.4f}" for x, y in poly)
        paths.append(f'  <path d="M {points} Z" {stroke} stroke-linejoin="round"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_in:.4f}in" height="{h_in:.4f}in" '
        f'viewBox="0 0 {w_in:.4f} {h_in:.4f}">\n'
        f"  <title>cut line, {spec.size_in:g} in {SHAPE_LABELS[art.shape]}</title>\n"
        + "\n".join(paths)
        + "\n</svg>\n"
    )
