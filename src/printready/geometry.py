"""Pure mask geometry shared by checks, fixes, the cut line and the proof.

Masks are HxW bool arrays. Distances are Euclidean, pixel centre to pixel centre, computed with
OpenCV's exact distance transform, so dilation by r px keeps every pixel whose centre lies
within r of a mask pixel. Physical scale (01-DESIGN.md, Units):
    ppi = subject_bbox_long_px / (size_in - 2 * profile.border_in)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np
from skimage.color import deltaE_ciede2000, rgb2lab

from printready.profile import Profile
from printready.types import Spec

# Algorithm settings (not label boundaries, so they live here rather than in the profile).
RING_FRAC = 0.02  # background ring = outer band, 2 % of the shorter canvas side
SMOOTH_SIGMA_IN = 0.01  # Gaussian sigma that smooths the cut outline, inches
SIMPLIFY_IN = 0.003  # polygon simplification tolerance for the cut line, inches
PARTIAL_ALPHA = (16, 239)  # soft-alpha band: partial-alpha pixels
SOLID_ALPHA = 240  # soft-alpha band: distance is measured to the nearest pixel at least this opaque


# ---------------------------------------------------------------- scale and boxes

def bbox(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """(x0, y0, x1, y1) of the True pixels, end exclusive; None if the mask is empty."""
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(mask.any(axis=0))
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def long_side_px(mask: np.ndarray) -> int:
    """Longest side of the mask's bounding box in px (0 if empty)."""
    box = bbox(mask)
    return 0 if box is None else max(box[2] - box[0], box[3] - box[1])


def ppi_for_long_side(long_px: float, spec: Spec, profile: Profile) -> float:
    """PPI when `long_px` pixels print across spec.size_in minus the standard border on both sides."""
    printable_in = spec.size_in - 2 * profile.border_in
    if printable_in <= 0:
        raise ValueError(f"a {spec.size_in} in sticker leaves no room inside a {profile.border_in} in border")
    return long_px / printable_in


def min_margin_px(mask: np.ndarray) -> int | None:
    """Smallest distance from the mask's bounding box to a canvas edge, px (None if empty)."""
    box = bbox(mask)
    if box is None:
        return None
    h, w = mask.shape
    return min(box[0], box[1], w - box[2], h - box[3])


# ---------------------------------------------------------------- morphology

def disk_kernel(radius_in: float, ppi: float) -> np.ndarray:
    """uint8 disc structuring element of `radius_in` inches at `ppi` (for OpenCV morphology)."""
    r = max(0, int(round(radius_in * ppi)))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def distance_to(mask: np.ndarray) -> np.ndarray:
    """float32 distance from every pixel to the nearest True pixel of `mask` (mask must be non-empty)."""
    return cv2.distanceTransform((~mask).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)


def dilate(mask: np.ndarray, radius_px: float) -> np.ndarray:
    """Grow by a disc of `radius_px` (clipped to the canvas)."""
    if radius_px <= 0 or not mask.any():
        return mask.copy()
    return distance_to(mask) <= radius_px


def erode(mask: np.ndarray, radius_px: float) -> np.ndarray:
    """Shrink by a disc of `radius_px`. The canvas edge is not treated as background."""
    if radius_px <= 0 or mask.all() or not mask.any():
        return mask.copy()
    return distance_to(~mask) > radius_px


def close(mask: np.ndarray, radius_px: float) -> np.ndarray:
    """Morphological closing with a disc of `radius_px`, computed on a padded canvas."""
    if radius_px <= 0:
        return mask.copy()
    pad = int(math.ceil(radius_px)) + 2
    padded = np.pad(mask, pad)
    return erode(dilate(padded, radius_px), radius_px)[pad:-pad, pad:-pad]


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill every background region not connected (4-neighbour) to the outside of the canvas."""
    h, w = mask.shape
    flood = np.zeros((h + 2, w + 2), np.uint8)
    flood[1:-1, 1:-1] = mask
    cv2.floodFill(flood, np.zeros((h + 4, w + 4), np.uint8), (0, 0), 2)
    return flood[1:-1, 1:-1] != 2


def smooth(mask: np.ndarray, sigma_px: float) -> np.ndarray:
    """Smooth an outline: Gaussian blur of the mask, thresholded at one half."""
    if sigma_px < 0.5:
        return mask.copy()
    return cv2.GaussianBlur(mask.astype(np.float32), (0, 0), sigma_px) >= 0.5


@dataclass
class Components:
    masks: list[np.ndarray]  # significant components, largest first
    specks: int  # components dropped as specks
    speck_px: int  # weighted area of the dropped specks


def components(mask: np.ndarray, min_area_px: float, area_of: np.ndarray | None = None) -> Components:
    """8-connected components of `mask`, dropping specks whose area is below `min_area_px`.

    Area is the count of `area_of` pixels inside each component (default: the component itself),
    so a dilated component is judged by how much real subject it holds.
    """
    n, labels = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)
    weight = mask if area_of is None else area_of
    areas = np.bincount(labels[weight], minlength=n)
    keep = [i for i in range(1, n) if areas[i] >= min_area_px]
    drop = [i for i in range(1, n) if areas[i] < min_area_px]
    keep.sort(key=lambda i: -areas[i])
    return Components(
        masks=[labels == i for i in keep],
        specks=len(drop),
        speck_px=int(sum(areas[i] for i in drop)),
    )


def cut_mask(
    subject: np.ndarray,
    ppi: float,
    border_in: float,
    close_in: float | None = None,
    speck_in2: float | None = None,
) -> np.ndarray:
    """The die-cut region: subject dilated by `border_in`, holes filled, specks dropped,
    optionally closed with a disc of diameter `close_in`, outline smoothed. Always contains the
    (non-speck) subject. Clipped to the canvas: pad first if the border must fit."""
    base = fill_holes(dilate(subject, border_in * ppi))
    if speck_in2:
        kept = components(base, speck_in2 * ppi**2, area_of=subject).masks
        base = np.logical_or.reduce(kept) if kept else np.zeros_like(base)
    cut = base
    if close_in:
        cut = fill_holes(close(cut, close_in * ppi / 2))
    cut = fill_holes(smooth(cut, SMOOTH_SIGMA_IN * ppi))
    return cut | (subject & base)


def outline_polygons(mask: np.ndarray, ppi: float) -> list[np.ndarray]:
    """Outer outlines of each piece of `mask` as simplified closed polygons, Nx2 float px
    (x, y at pixel centres)."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    eps = max(0.5, SIMPLIFY_IN * ppi)
    polys = []
    for contour in contours:
        poly = cv2.approxPolyDP(contour, eps, True).reshape(-1, 2)
        if len(poly) >= 3:
            polys.append(poly.astype(np.float64) + 0.5)
    return polys


# ---------------------------------------------------------------- measurements

def soft_alpha_p95_px(alpha: np.ndarray) -> float:
    """95th percentile distance (px) from each partial-alpha pixel (16..239) to the nearest pixel
    with alpha >= 240. 0 if there are no partial pixels; inf if nothing is solid."""
    lo, hi = PARTIAL_ALPHA
    partial = (alpha >= lo) & (alpha <= hi)
    if not partial.any():
        return 0.0
    solid = alpha >= SOLID_ALPHA
    if not solid.any():
        return math.inf
    return float(np.percentile(distance_to(solid)[partial], 95))


@dataclass
class EdgeRun:
    length_px: int
    edge: str  # "top" | "bottom" | "left" | "right" | "" when no run
    start: int  # position along the edge, px
    end: int  # exclusive

    def box(self, shape: tuple[int, ...]) -> tuple[int, int, int, int]:
        h, w = shape[:2]
        return {
            "top": (self.start, 0, self.end, 1),
            "bottom": (self.start, h - 1, self.end, h),
            "left": (0, self.start, 1, self.end),
            "right": (w - 1, self.start, w, self.end),
        }[self.edge]


def _longest_run(line: np.ndarray) -> tuple[int, int]:
    padded = np.concatenate([[0], line.astype(np.int8), [0]])
    diff = np.diff(padded)
    starts, ends = np.flatnonzero(diff == 1), np.flatnonzero(diff == -1)
    if starts.size == 0:
        return 0, 0
    i = int(np.argmax(ends - starts))
    return int(starts[i]), int(ends[i] - starts[i])


def longest_edge_run(mask: np.ndarray) -> EdgeRun:
    """Longest contiguous run of True pixels along any of the four canvas edges."""
    best = EdgeRun(0, "", 0, 0)
    for edge, line in (("top", mask[0]), ("bottom", mask[-1]), ("left", mask[:, 0]), ("right", mask[:, -1])):
        start, length = _longest_run(line)
        if length > best.length_px:
            best = EdgeRun(length, edge, start, start + length)
    return best


def edge_pixel_count(mask: np.ndarray) -> int:
    """Number of True pixels on the canvas border (corners counted once)."""
    border = np.zeros(mask.shape, bool)
    border[0, :] = border[-1, :] = border[:, 0] = border[:, -1] = True
    return int((mask & border).sum())


@dataclass
class Ring:
    uniform_frac: float  # share of ring pixels within delta_e of the dominant colour
    rgb: tuple[int, int, int]  # dominant ring colour
    lab: tuple[float, float, float]
    band_px: int


def ring_pixels(rgb: np.ndarray, band_frac: float = RING_FRAC) -> tuple[np.ndarray, int]:
    """The outer band of an HxWx3 image as Nx3, plus the band width in px."""
    h, w = rgb.shape[:2]
    b = max(1, int(round(band_frac * min(h, w))))
    parts = [rgb[:b], rgb[h - b:], rgb[b:h - b, :b], rgb[b:h - b, w - b:]]
    return np.concatenate([p.reshape(-1, 3) for p in parts]), b


def ring_uniformity(rgb: np.ndarray, delta_e: float, band_frac: float = RING_FRAC) -> Ring:
    """How much of the outer ring is one colour, by CIEDE2000.

    The dominant colour is seeded by the most common coarse RGB bin (32 levels per channel) and
    refined as the median CIELAB of that bin's pixels.
    """
    ring, b = ring_pixels(rgb, band_frac)
    keys = (ring[:, 0] // 32).astype(np.int32) * 64 + (ring[:, 1] // 32) * 8 + (ring[:, 2] // 32)
    in_mode = keys == np.bincount(keys).argmax()
    lab = rgb2lab(ring[None].astype(np.float64) / 255.0)[0]
    dominant = np.median(lab[in_mode], axis=0)
    de = deltaE_ciede2000(lab, np.broadcast_to(dominant, lab.shape))
    rgb_dom = np.median(ring[in_mode], axis=0).round().astype(int)
    return Ring(
        uniform_frac=float(np.mean(de <= delta_e)),
        rgb=(int(rgb_dom[0]), int(rgb_dom[1]), int(rgb_dom[2])),
        lab=(float(dominant[0]), float(dominant[1]), float(dominant[2])),
        band_px=b,
    )
