"""Image input/output (chunk K1).

Loads PNG, JPG and WebP into an HxWx4 uint8 RGBA array, applies the EXIF orientation, and
refuses files above the profile's upload limit before decoding them.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


class ImageLoadError(ValueError):
    """The file cannot be used: too large, not decodable, or not PNG/JPG/WebP."""


def load_rgba(path: str | Path, max_mb: float) -> np.ndarray:
    """Read `path` and return HxWx4 uint8 RGBA with EXIF orientation applied.

    Raises ImageLoadError (with a plain reason) if the file exceeds `max_mb` or does not decode.
    Opaque images get alpha 255 everywhere.
    """
    raise NotImplementedError("K1")


def save_png(rgba: np.ndarray, path: str | Path) -> None:
    """Write an HxWx4 uint8 RGBA array as a PNG, creating parent directories."""
    raise NotImplementedError("K1")
