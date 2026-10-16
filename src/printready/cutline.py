"""Die-cut line as SVG: the outline of `art.cut`, in inches, magenta 0.5 pt stroke.

The SVG covers the whole canvas at Artwork.ppi (width = canvas px / ppi inches), so it lines up
with fixed.png at the same physical size.
"""

from __future__ import annotations

from printready.geometry import outline_polygons
from printready.profile import PT_PER_IN, Profile
from printready.types import Artwork, Spec

CUT_COLOUR = "#ff00ff"
CUT_STROKE_PT = 0.5


def cutline_svg(art: Artwork, spec: Spec, profile: Profile) -> str:
    """Closed path(s), one per piece of the cut, simplified, coordinates in inches."""
    if art.cut is None:
        raise ValueError("art.cut is None: build the cut mask (add_border) before drawing the cut line")
    ppi = art.ppi
    w_in, h_in = art.width / ppi, art.height / ppi
    paths = []
    for poly in outline_polygons(art.cut, ppi):
        points = " L ".join(f"{x / ppi:.4f} {y / ppi:.4f}" for x, y in poly)
        paths.append(
            f'  <path d="M {points} Z" fill="none" stroke="{CUT_COLOUR}" '
            f'stroke-width="{CUT_STROKE_PT / PT_PER_IN:.5f}" stroke-linejoin="round"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w_in:.4f}in" height="{h_in:.4f}in" '
        f'viewBox="0 0 {w_in:.4f} {h_in:.4f}">\n'
        f"  <title>die-cut line, {spec.size_in:g} in {spec.product.replace('_', '-')}</title>\n"
        + "\n".join(paths)
        + "\n</svg>\n"
    )
