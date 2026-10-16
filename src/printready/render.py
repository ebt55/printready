"""Proof and overlay images (PIL, RGB)."""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from printready.geometry import cut_mask, outline_polygons
from printready.profile import Profile
from printready.types import SUBJECT_ALPHA, Artwork, Report, Spec

MAGENTA = (255, 0, 255)
STATUS_COLOURS = {"fail": (220, 30, 30), "warn": (240, 150, 0)}
CHECKER = (255, 255, 255), (222, 222, 222)
PREVIEW_MARGIN_PX = 4


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except (TypeError, OSError):  # Pillow without FreeType
        return ImageFont.load_default()


def checkerboard(h: int, w: int) -> np.ndarray:
    """HxWx3 uint8 light checkerboard (shows where the sticker is transparent)."""
    square = max(8, min(h, w) // 24)
    board = ((np.arange(h) // square) % 2)[:, None] ^ ((np.arange(w) // square) % 2)[None, :]
    return np.where(board[..., None].astype(bool), np.uint8(CHECKER[1][0]), np.uint8(CHECKER[0][0])).repeat(3, axis=2)


def composite(rgba: np.ndarray, under: np.ndarray) -> np.ndarray:
    """Alpha-composite RGBA over an HxWx3 background (integer maths, rounded)."""
    a = rgba[..., 3:4].astype(np.uint16)
    out = rgba[..., :3].astype(np.uint16) * a + under.astype(np.uint16) * (255 - a) + 127
    return (out // 255).astype(np.uint8)


def render_overlay(art: Artwork, report: Report) -> Image.Image:
    """The art over a checkerboard, with a box and label for every warn/fail finding that has
    boxes, and a banner listing every warn/fail check."""
    h, w = art.height, art.width
    img = Image.fromarray(composite(art.rgba, checkerboard(h, w)))
    flagged = [f for f in report.findings if f.status in STATUS_COLOURS]
    line = max(2, max(h, w) // 300)
    font = _font(max(12, max(h, w) // 45))
    min_box = max(6, max(h, w) // 60)
    draw = ImageDraw.Draw(img)
    for f in flagged:
        for x0, y0, x1, y1 in f.boxes:
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            hw, hh = max((x1 - x0) / 2, min_box), max((y1 - y0) / 2, min_box)
            rect = (max(0, cx - hw), max(0, cy - hh), min(w - 1, cx + hw), min(h - 1, cy + hh))
            draw.rectangle(rect, outline=STATUS_COLOURS[f.status], width=line)
            draw.text((rect[0] + line + 2, rect[1] + line + 1), f.check, fill=STATUS_COLOURS[f.status], font=font)
    if not flagged:
        return img
    text = "   ".join(f"{f.status.upper()} {f.check}" for f in flagged)
    banner_h = int(font.size * 1.8) if hasattr(font, "size") else 24
    out = Image.new("RGB", (w, h + banner_h), (255, 255, 255))
    out.paste(img, (0, banner_h))
    worst = "fail" if any(f.status == "fail" for f in flagged) else "warn"
    ImageDraw.Draw(out).text((8, banner_h // 5), text, fill=STATUS_COLOURS[worst], font=font)
    return out


def render_proof(art: Artwork, spec: Spec, profile: Profile) -> Image.Image:
    """Art plus the white border region (art.cut) over a checkerboard, the magenta cut line, and
    a size label. Without art.cut, builds a preview cut with geometry.cut_mask on a padded copy
    (the standard border, closing and speck rule); `art` is never modified."""
    rgba, cut = art.rgba, art.cut
    ppi = art.ppi
    if cut is None:
        subject = art.subject if art.subject is not None else rgba[..., 3] >= SUBJECT_ALPHA
        pad = int(math.ceil(profile.border_in * ppi)) + PREVIEW_MARGIN_PX
        rgba = np.pad(rgba, ((pad, pad), (pad, pad), (0, 0)))
        subject = np.pad(subject, pad)
        cut = cut_mask(subject, ppi, profile.border_in, profile.min_neck_in, profile.speck_max_in2)
    h, w = cut.shape
    base = checkerboard(h, w)
    base[cut] = 255
    img = Image.fromarray(composite(rgba, base))
    draw = ImageDraw.Draw(img)
    width = max(2, round(profile.pt_to_px(0.5, ppi)))
    for poly in outline_polygons(cut, ppi):
        pts = [tuple(p) for p in poly]
        draw.line(pts + [pts[0]], fill=MAGENTA, width=width, joint="curve")

    font = _font(max(14, w // 28))
    label = f"{spec.size_in:.1f} in die-cut, {ppi:.0f} PPI"
    label_h = int(getattr(font, "size", 16) * 2)
    out = Image.new("RGB", (w, h + label_h), (255, 255, 255))
    out.paste(img, (0, 0))
    ImageDraw.Draw(out).text((10, h + label_h // 4), label, fill=(0, 0, 0), font=font)
    return out
