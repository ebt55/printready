"""Die-cut line as SVG (chunk K1)."""

from __future__ import annotations

from printready.profile import Profile
from printready.types import Artwork, Spec


def cutline_svg(art: Artwork, spec: Spec, profile: Profile) -> str:
    """Trace `art.cut` into closed path(s) in inches at the ordered size, magenta 0.5 pt stroke."""
    raise NotImplementedError("K1")
