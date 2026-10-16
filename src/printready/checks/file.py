"""`file`: the image decodes, is under the upload limit, and is at least 64 px a side."""

from __future__ import annotations

from printready.profile import BYTES_PER_MB, Profile
from printready.types import Artwork, Finding, Spec

MIN_SIDE_PX = 64


def check_file(art: Artwork, spec: Spec, profile: Profile) -> Finding:
    w, h = art.width, art.height
    nbytes = art.meta.get("bytes")
    fmt = art.meta.get("format")
    measured = {
        "width_px": w,
        "height_px": h,
        "format": fmt,
        "bytes": nbytes,
        "max_bytes": profile.max_upload_bytes,
    }
    if nbytes is not None and nbytes > profile.max_upload_bytes:
        mb = nbytes / BYTES_PER_MB
        msg = f"The file is {mb:.1f} MB, over the {profile.max_upload_mb:g} MB upload limit; please export a smaller file."
        return Finding("file", "fail", msg, measured, "customer")
    if min(w, h) < MIN_SIDE_PX:
        msg = f"The image is only {w} x {h} px; it needs at least {MIN_SIDE_PX} px on each side."
        return Finding("file", "fail", msg, measured, "none")
    if art.subject is not None and not art.subject.any():
        return Finding("file", "fail", "The image is fully transparent, so there is nothing to print.", measured, "none")
    details = ", ".join(part for part in (f"{w} x {h} px", fmt, _size(nbytes)) if part)
    return Finding("file", "pass", f"The file opens fine ({details}).", measured, "none")


def _size(nbytes: int | None) -> str | None:
    if nbytes is None:
        return None
    return f"{nbytes / BYTES_PER_MB:.1f} MB" if nbytes >= 100_000 else f"{max(1, round(nbytes / 1000))} KB"


def load_failure(reason: str) -> Finding:
    """The `file` finding for an image that could not be opened at all."""
    return Finding("file", "fail", f"The file could not be opened: {reason}.", {"error": reason}, "none")
