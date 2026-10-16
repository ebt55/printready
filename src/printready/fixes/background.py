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

from printready.fixes._common import copy_with, refuse
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


def flood_from_edge(candidate: np.ndarray) -> np.ndarray:
    """Pixels of `candidate` 4-connected to the canvas border (4-connectivity cannot leak
    through a diagonal gap in an outline)."""
    _, labels = cv2.connectedComponents(candidate.astype(np.uint8), connectivity=4)
    border = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    seeds = np.unique(border[border > 0])
    return np.isin(labels, seeds)


def _feather(rgb: np.ndarray, keep: np.ndarray, bg_rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """RGB and alpha after removal, with the 1 px ring of kept pixels that touch removed ones
    feathered. An edge pixel is modelled as coverage * foreground + (1 - coverage) * background,
    where the foreground is the mean colour of nearby interior pixels: coverage becomes its alpha
    and the background share is subtracted from its colour, so no background fringe remains."""
    alpha = np.where(keep, 255, 0).astype(np.uint8)
    out = np.where(keep[..., None], rgb, 0).astype(np.uint8)
    edge = keep & dilate(~keep, EDGE_RADIUS_PX)
    interior = (keep & ~edge).astype(np.float32)
    window = (INTERIOR_WINDOW_PX, INTERIOR_WINDOW_PX)
    colour_sum = cv2.blur(rgb.astype(np.float32) * interior[..., None], window)
    weight_sum = cv2.blur(interior, window)

    observed = rgb[edge].astype(np.float32)
    has_interior = weight_sum[edge] > 1e-6
    foreground = np.where(
        has_interior[:, None], colour_sum[edge] / np.maximum(weight_sum[edge], 1e-6)[:, None], observed
    )
    fg_minus_bg = foreground - bg_rgb
    contrast_sq = np.sum(fg_minus_bg * fg_minus_bg, axis=1)
    # coverage = projection of (observed - background) onto (foreground - background)
    coverage = np.sum((observed - bg_rgb) * fg_minus_bg, axis=1) / np.maximum(contrast_sq, 1e-6)
    coverage = np.where(has_interior & (contrast_sq >= MIN_CONTRAST_RGB**2), np.clip(coverage, 0.0, 1.0), 1.0)
    unblended = np.clip((observed - (1.0 - coverage)[:, None] * bg_rgb) / np.maximum(coverage, 1e-3)[:, None], 0, 255)
    alpha[edge] = np.round(255 * coverage).astype(np.uint8)
    out[edge] = np.round(unblended).astype(np.uint8)
    out[alpha == 0] = 0
    return out, alpha


def remove_background(art: Artwork, spec: Spec, profile: Profile) -> FixResult:
    """Remove a solid background and set `subject` and `ppi`. Refused when the art is already
    transparent, the ring is not one colour, the result is scattered (more than max_pieces parts or
    max_specks specks), or it would remove less than 2 % or more than 95 % of the image."""
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

    background = flood_from_edge(delta_e_to(rgb, ring.lab) <= profile.bg_delta_e)
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
    new = copy_with(art, rgba=np.dstack([out_rgb, alpha]), subject=subject, ppi=ppi, border_in=None, cut=None)
    note = f"Removed the solid {colour} background ({removed_frac:.0%} of the image)."
    return FixResult(art=new, ok=True, note=note, measured=measured)
