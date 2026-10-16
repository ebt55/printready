"""Image input/output: PNG, JPG and WebP -> RGBA uint8 Artwork, with EXIF orientation applied.

The upload limit is not enforced here: the `file` check reads the byte size from `art.meta`.
A file that cannot be decoded raises ImageLoadError; callers turn that into a `file` fail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from printready.geometry import long_side_px, ppi_for_long_side
from printready.profile import Profile
from printready.types import SUBJECT_ALPHA, Artwork, Spec

FORMATS = {"PNG": "PNG", "JPEG": "JPEG", "MPO": "JPEG", "WEBP": "WEBP"}  # PIL format -> ours
REAL_ALPHA_BELOW = 250  # alpha values under this count as transparent-ish...
REAL_ALPHA_MIN_FRAC = 0.01  # ...and the image has real alpha if more than 1 % of pixels are


class ImageLoadError(ValueError):
    """The file cannot be used: unreadable, not decodable, or not PNG/JPG/WebP."""


def has_real_alpha(alpha: np.ndarray) -> bool:
    return float(np.mean(alpha < REAL_ALPHA_BELOW)) > REAL_ALPHA_MIN_FRAC


def artwork_from_rgba(
    rgba: np.ndarray, spec: Spec, profile: Profile, meta: dict[str, Any] | None = None
) -> Artwork:
    """Wrap an HxWx4 uint8 array as Artwork: subject and ppi from alpha if it is real, else
    subject None and ppi from the full canvas."""
    meta = dict(meta or {})
    real = has_real_alpha(rgba[..., 3])
    meta["real_alpha"] = real
    subject = rgba[..., 3] >= SUBJECT_ALPHA if real else None
    long_px = long_side_px(subject) if subject is not None else 0
    if long_px == 0:  # opaque, or nothing visible: scale from the canvas
        long_px = max(rgba.shape[:2])
    return Artwork(rgba=rgba, subject=subject, ppi=ppi_for_long_side(long_px, spec, profile), meta=meta)


def load_artwork(path: str | Path, spec: Spec, profile: Profile) -> Artwork:
    """Decode `path` (PNG/JPG/WebP), apply EXIF orientation, and return Artwork with meta
    {path, bytes, format, real_alpha}. Raises ImageLoadError with a plain reason."""
    path = Path(path)
    try:
        nbytes = path.stat().st_size
    except OSError as exc:
        raise ImageLoadError(f"cannot read {path.name} ({exc.strerror or exc})") from exc
    try:
        with Image.open(path) as im:
            fmt = FORMATS.get(im.format or "")
            if fmt is None:
                raise ImageLoadError(f"{path.name} is {im.format or 'an unknown format'}, not PNG, JPG or WebP")
            upright = ImageOps.exif_transpose(im)
            rgba = np.array(upright.convert("RGBA"), dtype=np.uint8)
    except ImageLoadError:
        raise
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ImageLoadError(f"{path.name} could not be decoded ({exc})") from exc
    meta = {"path": str(path), "bytes": nbytes, "format": fmt}
    return artwork_from_rgba(rgba, spec, profile, meta)


def save_png(rgba: np.ndarray, path: str | Path) -> None:
    """Write an HxWx4 uint8 RGBA array as a PNG, creating parent directories."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rgba).save(path, format="PNG")
