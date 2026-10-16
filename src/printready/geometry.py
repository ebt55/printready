"""Mask geometry shared by checks, fixes and the cut line (chunk K1).

Physical scale (01-DESIGN.md, "Units and the core measurement"):
    ppi = subject_bbox_long_px / (spec.size_in - 2 * border_in)
Every physical threshold converts to pixels with that ppi. These helpers are internal and K1 may
reshape them; the public contract lives in types.py.
"""

from __future__ import annotations

import numpy as np

from printready.profile import Profile
from printready.types import Artwork, Spec


def subject_bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Bounding box (x0, y0, x1, y1), exclusive end, of the True pixels; None if the mask is empty."""
    raise NotImplementedError("K1")


def ppi_at_size(art: Artwork, spec: Spec, profile: Profile) -> float:
    """Pixels per inch when the subject (the whole canvas while opaque) prints at spec.size_in."""
    raise NotImplementedError("K1")


def dilate(mask: np.ndarray, radius_px: float) -> np.ndarray:
    """Grow a bool mask by a disk of `radius_px`."""
    raise NotImplementedError("K1")


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill enclosed holes of a bool mask (background regions that do not touch the canvas edge)."""
    raise NotImplementedError("K1")


def components(mask: np.ndarray, min_area_px: int) -> list[np.ndarray]:
    """Connected components of a bool mask, largest first, dropping specks below `min_area_px`."""
    raise NotImplementedError("K1")
