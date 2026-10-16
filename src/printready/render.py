"""Proof and overlay images (chunk K1)."""

from __future__ import annotations

from PIL import Image

from printready.profile import Profile
from printready.types import Artwork, Report, Spec


def render_proof(art: Artwork, spec: Spec, profile: Profile) -> Image.Image:
    """Art plus white border over a checkerboard, magenta cut line, and a size label."""
    raise NotImplementedError("K1")


def render_overlay(art: Artwork, report: Report) -> Image.Image:
    """The original art with each finding's boxes and a short label drawn over it."""
    raise NotImplementedError("K1")
