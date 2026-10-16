"""remove_background: solid (uniform-ring) backgrounds only.

Flood fill from the canvas edge in CIELAB within bg_delta_e of the dominant ring colour,
keep the rest, drop specks (same rule as the islands check), then feather the 1 px edge:
each edge pixel gets alpha from projecting its colour between the background colour and the
nearby interior subject colour, and the background colour is unblended from it. Sets
`subject` and `ppi` (the one fix allowed to set ppi).
"""

from __future__ import annotations

import cv2
import numpy as np
from printready.fixes._common import evolve, refuse
from printready.geometry import (
    components,
    count_pieces,
    delta_e_to,
    dilate,
    fill_holes,
    long_side_px,
    ppi_for_long_side,
    ring_uniformity,
)
from printready.profile import Profile
from printready.types import SUBJECT_ALPHA, Artwork, FixResult, Spec

MIN_REMOVED_FRAC = 0.02
MAX_REMOVED_FRAC = 0.95
EDGE_RADIUS_PX = 1.5  # kept pixels within this of removed ones form the 1 px feather ring (8-neighbour)
INTERIOR_WINDOW_PX = 5  # window for the nearby interior subject colour
MIN_CONTRAST_RGB = 30.0  # below this subject/background RGB distance, alpha cannot be estimated: keep opaque


def background_lab_distance(rgb: np.ndarray, lab_colour: tuple[float, float, float]) -> np.ndarray:
    """CIEDE2000 distance of every pixel of a ...x3 uint8 array from one CIELAB colour."""
    return delta_e_to(rgb, lab_colour)


def flood_from_edge(candidate: np.ndarray) -> np.ndarray:
    """Pixels of `candidate` 4-connected to the canvas border (4-connectivity cannot leak
    through a diagonal gap in an outline)."""
    _, labels = cv2.connectedComponents(candidate.astype(np.uint8), connectivity=4)
    border = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    seeds = np.unique(border[border > 0])
    return np.isin(labels, seeds)


def _feather(rgb: np.ndarray, keep: np.ndarray, bg_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Alpha and unblended colour for the kept pixels that touch removed ones."""
    alpha = np.where(keep, 255, 0).astype(np.uint8)
    out = np.where(keep[..., None], rgb, 0).astype(np.uint8)
    edge = keep & dilate(~keep, EDGE_RADIUS_PX)
    interior = (keep & ~edge).astype(np.float32)
    window = (INTERIOR_WINDOW_PX, INTERIOR_WINDOW_PX)
    num = cv2.blur(rgb.astype(np.float32) * interior[..., None], window)
    den = cv2.blur(interior, window)

    c = rgb[edge].astype(np.float32)
    has_f = den[edge] > 1e-6
    f = np.where(has_f[:, None], num[edge] / np.maximum(den[edge], 1e-6)[:, None], c)
    fb = f - bg_rgb
    span = np.sum(fb * fb, axis=1)
    a = np.sum((c - bg_rgb) * fb, axis=1) / np.maximum(span, 1e-6)
    a = np.where(has_f & (span >= MIN_CONTRAST_RGB**2), np.clip(a, 0.0, 1.0), 1.0)
    safe = np.maximum(a, 1e-3)[:, None]
    unblended = np.clip((c - (1.0 - a)[:, None] * bg_rgb) / safe, 0, 255)
    alpha[edge] = np.round(255 * a).astype(np.uint8)
    out[edge] = np.round(unblended).astype(np.uint8)
    out[alpha == 0] = 0
    return out, alpha


def remove_background(art: Artwork, spec: Spec, profile: Profile) -> FixResult:
    if art.subject is not None:
        return refuse(art, "The background is already transparent; nothing to remove.")
    rgb = art.rgba[..., :3]
    ring = ring_uniformity(rgb, profile.bg_delta_e)
    colour = "#{:02x}{:02x}{:02x}".format(*ring.rgb)
    measured = {"bg_hex": colour, "bg_rgb": list(ring.rgb), "ring_uniform_frac": round(ring.uniform_frac, 4)}
    if ring.uniform_frac < profile.bg_ring_uniform_frac:
        return refuse(
            art,
            f"The background is not one colour (only {ring.uniform_frac:.0%} of the edge matches), "
            "so it needs a person.",
            **measured,
        )

    background = flood_from_edge(background_lab_distance(rgb, ring.lab) <= profile.bg_delta_e)
    keep = ~background
    if not keep.any():
        return refuse(art, "Removing the background would leave nothing.", removed_frac=1.0, **measured)
    ppi0 = ppi_for_long_side(long_side_px(keep), spec, profile)
    region = fill_holes(dilate(keep, profile.border_in * ppi0))
    speck_px = profile.speck_max_in2 * ppi0**2
    found = components(region, speck_px, area_of=keep)
    pieces, specks = len(found.masks), count_pieces(keep, speck_px)[1]
    measured.update(pieces=pieces, max_pieces=int(profile.max_pieces), specks=specks, max_specks=int(profile.max_specks))
    if pieces > profile.max_pieces or specks > profile.max_specks:
        return refuse(
            art,
            "The background is not one flat colour (stars, texture or scattered detail), so the cut line needs a person.",
            **measured,
        )
    if found.masks:
        keep &= np.logical_or.reduce(found.masks)
    removed_frac = 1.0 - float(keep.mean())
    measured.update(removed_frac=round(removed_frac, 4), specks_dropped=found.specks)
    if not MIN_REMOVED_FRAC <= removed_frac <= MAX_REMOVED_FRAC:
        return refuse(
            art,
            f"Removing the {colour} background would take away {removed_frac:.0%} of the image, "
            f"outside the {MIN_REMOVED_FRAC:.0%}-{MAX_REMOVED_FRAC:.0%} range we trust.",
            **measured,
        )

    out_rgb, alpha = _feather(rgb, keep, np.asarray(ring.rgb, np.float32))
    subject = alpha >= SUBJECT_ALPHA
    ppi = ppi_for_long_side(long_side_px(subject), spec, profile)
    measured["ppi"] = round(ppi, 2)
    new = evolve(art, rgba=np.dstack([out_rgb, alpha]), subject=subject, ppi=ppi, border_in=None, cut=None)
    note = f"Removed the solid {colour} background ({removed_frac:.0%} of the image)."
    return FixResult(art=new, ok=True, note=note, measured=measured)
