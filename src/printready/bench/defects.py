"""Defect families. Each builder takes one planned sample, plants its defect on base art, and
returns the image, the ground-truth subject mask and the family's ground-truth quantities.

Labels never come from here directly: `labels.py` turns the quantities into statuses. A builder
raises `Resample` when a random draw cannot produce a valid sample; the generator then draws again
from the same seeded stream and counts it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Callable

import numpy as np
from PIL import Image
from skimage import measure
from skimage.color import deltaE_ciede2000, rgb2lab

from printready.bench import text as txt
from printready.bench.bases import (
    CANVAS_LONG,
    CANVAS_SHORT,
    MARGIN_FRAC,
    MARGIN_SAFETY_PX,
    N_BASES,
    Base,
    Placement,
    hsv,
    make_base,
    render,
    scaled_placement,
    text_fits,
)
from printready.bench.labels import Thresholds
from printready.bench.shapes import alpha_u8, bbox
from printready.types import SUBJECT_ALPHA

RGB = tuple[int, int, int]

# --- the family table (03-EVAL section 1) -------------------------------------------------------

RESOLUTION_PPI = (100, 125, 180, 240, 350, 420)  # 7 bases each
BACKGROUNDS = ("white", "saturated", "near_white_noise", "gradient", "texture")  # 8 each
AUTO_BACKGROUNDS = ("white", "saturated", "near_white_noise")
ISLAND_GAPS_IN = (0.10, 0.15, 0.27, 0.40, 0.80)  # 8 each
SOFT_RAMPS_IN = (0.01, 0.06, 0.12)  # 8 each
EDGE_CASES = {  # target longest edge run, inches (8 each)
    "a": (0.02, 0.07),  # touching: under 0.09 in
    "b": (0.22, 0.38),  # 0.2-0.4 in
    "c": (0.65, 1.5),  # cut off: over 0.6 in
}
TEXT_CAP_PT = (2.5, 3.0, 8.0, 12.0)  # 4 words each

NOISE_DE_MAX = 4.0  # near-white noise: max CIEDE2000 from the mean (well inside bg_delta_e 8)
PERSON_RING_UNIFORMITY_MAX = 0.6  # gradients and textures stay below this
MIN_EDGE_CONTRAST_DE = 30.0  # solid backgrounds differ this much from the subject's rim colour
RING_FRAC = 0.02  # the ring is the outer 2 % band


class Resample(Exception):
    """This draw cannot make a valid sample; draw again."""


@dataclass(frozen=True)
class PlanItem:
    id: str
    family: str
    index: int
    bases: tuple[int, ...]
    param: dict[str, Any] = field(compare=False)


@dataclass
class Planted:
    rgba: np.ndarray
    subject: np.ndarray  # ground-truth subject mask (bool)
    opaque: bool
    bases: list[int]
    kind: str
    param: dict[str, Any]
    gt: dict[str, Any]  # family ground truth; the generator adds the common measurements
    analytic_bbox: tuple[float, float, float, float] | None  # None when the canvas crops the art
    parts: list[np.ndarray] | None = None  # islands: each part's mask (for tests)


@dataclass(frozen=True)
class Context:
    seed: int
    th: Thresholds
    attempt: int = 0
    size_in: float = 3.0

    def base(self, index: int) -> Base:
        return _base(self.seed, index % N_BASES)

    @property
    def printable_in(self) -> float:
        return self.th.printable_in(self.size_in)


@lru_cache(maxsize=128)
def _base(seed: int, index: int) -> Base:
    return make_base(seed, index)


def subject_of(rgba: np.ndarray) -> np.ndarray:
    return rgba[..., 3] >= SUBJECT_ALPHA


def _text_gt(r) -> dict[str, Any]:
    return {"word": r.word, "cap_height_px": r.cap_px} if r.word else {}


def _planted(r, base: Base, item: PlanItem, gt: dict | None = None, param: dict | None = None) -> Planted:
    return Planted(r.rgba, subject_of(r.rgba), False, [base.index], base.kind,
                   dict(param if param is not None else item.param), {**_text_gt(r), **(gt or {})}, r.bbox)


# --- colour ---------------------------------------------------------------------------------------


def lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB uint8 (..., 3) -> CIELAB."""
    return rgb2lab(np.asarray(rgb, dtype=np.float64) / 255.0)


def delta_e(a: RGB, b: RGB) -> float:
    return float(deltaE_ciede2000(lab(np.array([a])), lab(np.array([b])))[0])


def _unique_colours(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    flat = rgb.reshape(-1, 3).astype(np.int64)
    packed = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
    values, counts = np.unique(packed, return_counts=True)
    colours = np.stack([(values >> 16) & 255, (values >> 8) & 255, values & 255], axis=1)
    return colours.astype(np.uint8), counts


def max_de_from_mean(rgb: np.ndarray) -> float:
    """Largest CIEDE2000 distance of any pixel from the mean colour (exact, via unique colours)."""
    colours, _ = _unique_colours(rgb)
    mean = rgb.reshape(-1, 3).mean(axis=0)
    return float(deltaE_ciede2000(lab(mean[None]), lab(colours)).max())


def ring(rgb: np.ndarray, frac: float = RING_FRAC) -> np.ndarray:
    """The outer band of the canvas, `frac` of the short side wide, as (N, 3) pixels."""
    h, w = rgb.shape[:2]
    b = max(1, math.ceil(frac * min(h, w)))
    return np.concatenate([rgb[:b].reshape(-1, 3), rgb[-b:].reshape(-1, 3),
                           rgb[b:-b, :b].reshape(-1, 3), rgb[b:-b, -b:].reshape(-1, 3)])


def ring_uniformity(pixels: np.ndarray, tol: float, rng: np.random.Generator,
                    n_samples: int = 20000, n_candidates: int = 48) -> float:
    """Upper estimate of the share of ring pixels within `tol` CIEDE2000 of one colour: the best
    over candidate colours (the mean, the most common colour and colours drawn from the ring)."""
    colours, counts = _unique_colours(pixels)
    if len(colours) == 1:
        return 1.0
    if len(pixels) > n_samples:
        pixels = pixels[rng.choice(len(pixels), n_samples, replace=False)]
    sample_lab = lab(pixels)
    candidates = [pixels.mean(axis=0), colours[np.argmax(counts)].astype(np.float64)]
    picks = rng.choice(len(colours), min(n_candidates, len(colours)), replace=False, p=counts / counts.sum())
    candidates += [colours[i].astype(np.float64) for i in picks]
    best = 0.0
    for cand in candidates:
        de = deltaE_ciede2000(np.broadcast_to(lab(cand[None]), sample_lab.shape), sample_lab)
        best = max(best, float(np.mean(de <= tol)))
    return best


# --- families ------------------------------------------------------------------------------------


def clean(item: PlanItem, rng: np.random.Generator, ctx: Context) -> Planted:
    base = ctx.base(item.bases[0])
    return _planted(render(base), base, item)


def resolution(item: PlanItem, rng: np.random.Generator, ctx: Context) -> Planted:
    """Re-render the base so its subject bbox long side is ppi x printable inches. The art is
    procedural, so this is an ideal resample of the same design (exact one-pixel edges)."""
    base = ctx.base(item.bases[0])
    placement = scaled_placement(base, item.param["ppi"] * ctx.printable_in)
    return _planted(render(base, placement), base, item)


def _gradient(rng: np.random.Generator, h: int, w: int) -> tuple[np.ndarray, dict]:
    while True:
        c1 = hsv(rng.uniform(), rng.uniform(0.4, 0.9), rng.uniform(0.55, 0.98))
        c2 = hsv(rng.uniform(), rng.uniform(0.4, 0.9), rng.uniform(0.55, 0.98))
        if delta_e(c1, c2) >= 50:
            break
    angle = rng.uniform(0, 2 * math.pi)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
    t = xx * math.cos(angle) + yy * math.sin(angle)
    t = (t - t.min()) / (t.max() - t.min())
    rgb = np.asarray(c1) + (np.asarray(c2) - np.asarray(c1)) * t[..., None]
    info = {"colours": [list(c1), list(c2)], "angle_deg": math.degrees(angle)}
    return np.floor(rgb + 0.5).astype(np.uint8), info


def _value_noise(rng: np.random.Generator, h: int, w: int, cells: int) -> np.ndarray:
    grid = rng.random((cells + 1, cells + 1)).astype(np.float32)
    return np.asarray(Image.fromarray(grid).resize((w, h), Image.Resampling.BICUBIC), dtype=np.float64)


def _texture(rng: np.random.Generator, h: int, w: int) -> tuple[np.ndarray, dict]:
    while True:
        palette = [hsv(rng.uniform(), rng.uniform(0.35, 0.85), rng.uniform(0.45, 0.98)) for _ in range(3)]
        if min(delta_e(a, b) for a, b in ((palette[0], palette[1]), (palette[1], palette[2]),
                                          (palette[0], palette[2]))) >= 35:
            break
    coarse = _value_noise(rng, h, w, int(rng.integers(4, 7)))
    fine = _value_noise(rng, h, w, int(rng.integers(10, 16)))
    n = 0.6 * coarse + 0.4 * fine
    n = (n - n.min()) / (n.max() - n.min()) * 2.0  # 0..2 across the three palette colours
    lo = np.clip(np.floor(n).astype(int), 0, 1)
    frac = (n - lo)[..., None]
    pal = np.asarray(palette, dtype=np.float64)
    rgb = pal[lo] * (1 - frac) + pal[lo + 1] * frac
    rgb += rng.integers(-8, 9, size=rgb.shape)  # grain
    return np.clip(np.floor(rgb + 0.5), 0, 255).astype(np.uint8), {"colours": [list(c) for c in palette]}


def background(item: PlanItem, rng: np.random.Generator, ctx: Context) -> Planted:
    base = ctx.base(item.bases[0])
    r = render(base)
    h, w = r.rgba.shape[:2]
    kind = item.param["background"]
    info: dict[str, Any] = {}
    if kind == "white":
        bg = np.full((h, w, 3), 255, dtype=np.uint8)
    elif kind == "saturated":
        colour = hsv(rng.uniform(), rng.uniform(0.8, 1.0), rng.uniform(0.75, 1.0))
        bg = np.empty((h, w, 3), dtype=np.uint8)
        bg[...] = colour
        info["colours"] = [list(colour)]
    elif kind == "near_white_noise":
        # Shared lightness jitter plus a little per-channel jitter: about 3.5 CIEDE2000 at most.
        mean = rng.integers(240, 251, size=3)
        noise = rng.integers(-6, 7, size=(h, w, 1)) + rng.integers(-2, 3, size=(h, w, 3))
        bg = np.clip(mean + noise, 0, 255).astype(np.uint8)
        info.update(colours=[mean.tolist()], noise_rgb=[6, 2])
    elif kind == "gradient":
        bg, info = _gradient(rng, h, w)
    else:
        bg, info = _texture(rng, h, w)

    tol = ctx.th.bg_delta_e
    gt: dict[str, Any] = {"background": kind}
    pixels = ring(bg)
    gt["ring_uniformity"] = ring_uniformity(pixels, tol, rng)
    gt["ring_de_max"] = max_de_from_mean(pixels)
    if kind in AUTO_BACKGROUNDS:
        gt["bg_de_max"] = max_de_from_mean(bg)
        if gt["bg_de_max"] > NOISE_DE_MAX:
            raise Resample(f"background noise reaches {gt['bg_de_max']:.2f} CIEDE2000 from its mean")
        mean_rgb = tuple(int(round(v)) for v in bg.reshape(-1, 3).mean(axis=0))
        gt["edge_contrast_de"] = delta_e(mean_rgb, base.edge_color)
        if gt["edge_contrast_de"] < MIN_EDGE_CONTRAST_DE:
            raise Resample(f"background is only {gt['edge_contrast_de']:.1f} CIEDE2000 from the rim colour")
    elif gt["ring_uniformity"] >= PERSON_RING_UNIFORMITY_MAX:
        raise Resample(f"{kind} ring uniformity {gt['ring_uniformity']:.2f} "
                       f"is not below {PERSON_RING_UNIFORMITY_MAX}")

    a = r.rgba[..., 3:4].astype(np.float64) / 255.0
    comp = r.rgba[..., :3].astype(np.float64) * a + bg.astype(np.float64) * (1.0 - a)
    rgba = np.empty_like(r.rgba)
    rgba[..., :3] = np.floor(comp + 0.5).astype(np.uint8)
    rgba[..., 3] = 255
    param = {**item.param, **info}
    return Planted(rgba, subject_of(r.rgba), True, [base.index], base.kind, param,
                   {**_text_gt(r), **gt}, r.bbox)


def islands(item: PlanItem, rng: np.random.Generator, ctx: Context) -> Planted:
    """Two bases side by side, `gap_in` apart. A's rightmost point and B's leftmost point share a
    y coordinate, so the shortest distance between the parts is exactly the horizontal gap (the
    x-projection never shrinks distances, and those two points realise it)."""
    a, b = ctx.base(item.bases[0]), ctx.base(item.bases[1])
    gap_in = item.param["gap_in"]
    long_px = rng.uniform(940.0, 990.0)
    ppi = long_px / ctx.printable_in
    gap = gap_in * ppi
    ax0, ay0, ax1, ay1 = bbox(a.silhouette)
    bx0, by0, bx1, by1 = bbox(b.silhouette)
    f = rng.uniform(0.42, 0.58)
    sa = f * (long_px - gap) / (ax1 - ax0)
    sb = (1 - f) * (long_px - gap) / (bx1 - bx0)
    _, pax, pay = a.silhouette.support(1.0, 0.0)  # A's rightmost point (art units)
    _, pbx, pby = b.silhouette.support(-1.0, 0.0)  # B's leftmost point
    # Layout with A's bbox left at x = 0 and A's reference at y = 0.
    oxa, oya = -sa * ax0, 0.0
    join_x, join_y = oxa + sa * pax, oya + sa * pay
    oxb, oyb = join_x + gap - sb * pbx, join_y - sb * pby
    top = min(oya + sa * ay0, oyb + sb * by0)
    bottom = max(oya + sa * ay1, oyb + sb * by1)
    height = bottom - top
    if height > 0.9 * long_px:
        raise Resample("the two parts stack taller than they are wide")
    W = CANVAS_LONG
    H = CANVAS_SHORT if (height <= (1 - 2 * MARGIN_FRAC) * CANVAS_SHORT - 2 * MARGIN_SAFETY_PX - 4
                         and rng.random() < 0.5) else CANVAS_LONG
    mx, my = MARGIN_FRAC * W + MARGIN_SAFETY_PX, MARGIN_FRAC * H + MARGIN_SAFETY_PX
    left = mx + rng.uniform(0, W - 2 * mx - long_px)
    dy = my + rng.uniform(0, H - 2 * my - height) - top
    ra = render(a, Placement(sa, oxa + left, oya + dy, W, H))
    rb = render(b, Placement(sb, oxb + left, oyb + dy, W, H))
    if np.any((ra.rgba[..., 3] > 0) & (rb.rgba[..., 3] > 0)):
        raise RuntimeError("islands parts overlap; layout bug")
    rgba = ra.rgba.copy()
    in_b = rb.rgba[..., 3] > 0
    rgba[in_b] = rb.rgba[in_b]
    gt = {"parts": 2, "gap_px": gap}
    words = [r.word for r in (ra, rb) if r.word]
    caps = [r.cap_px for r in (ra, rb) if r.word]
    if words:  # the smaller word decides a text-size label
        k = int(np.argmin(caps))
        gt.update(word=words[k], cap_height_px=caps[k])
    analytic = (left, top + dy, left + long_px, bottom + dy)
    return Planted(rgba, subject_of(rgba), False, [a.index, b.index], f"{a.kind}+{b.kind}",
                   dict(item.param), gt, analytic, parts=[subject_of(ra.rgba), subject_of(rb.rgba)])


def soft_alpha(item: PlanItem, rng: np.random.Generator, ctx: Context) -> Planted:
    """A linear alpha ramp exactly W px wide outside the opaque silhouette (a dark shadow halo or a
    coloured glow). Alpha >= 128 reaches W/2 out, so the subject bbox grows by W px."""
    base = ctx.base(item.bases[0])
    ppi0 = base.long_px() / ctx.printable_in
    width_px = max(1, round(item.param["ramp_in"] * ppi0))
    if item.param["style"] == "shadow":
        colour = (30, 30, 36)
    else:
        colour = hsv(rng.uniform(), rng.uniform(0.3, 0.6), 1.0)
    r = render(base, glow=(width_px, colour))
    x0, y0, x1, y1 = r.bbox
    half = width_px / 2.0
    param = {**item.param, "ramp_px": width_px, "colour": list(colour)}
    p = _planted(r, base, item, {"ramp_px": width_px}, param)
    p.analytic_bbox = (x0 - half, y0 - half, x1 + half, y1 + half)
    return p


def longest_runs(mask: np.ndarray) -> np.ndarray:
    """Longest run of True along the last axis, for each row of a 2-D bool array."""
    m = np.atleast_2d(mask)
    padded = np.zeros((m.shape[0], m.shape[1] + 2), dtype=np.int8)
    padded[:, 1:-1] = m
    step = np.diff(padded, axis=1)
    rows_s, starts = np.nonzero(step == 1)
    _, ends = np.nonzero(step == -1)
    out = np.zeros(m.shape[0], dtype=np.int64)
    np.maximum.at(out, rows_s, ends - starts)
    return out


def edge_runs(mask: np.ndarray) -> dict[str, int]:
    """Longest run of subject pixels along each canvas edge."""
    return {
        "top": int(longest_runs(mask[0])[0]),
        "bottom": int(longest_runs(mask[-1])[0]),
        "left": int(longest_runs(mask[:, 0])[0]),
        "right": int(longest_runs(mask[:, -1])[0]),
    }


def _shift(edge: str, depth: float, bb, W: int, H: int) -> tuple[float, float]:
    """Translation that pushes the bbox `depth` px past `edge`."""
    x0, y0, x1, y1 = bb
    return {
        "top": (0.0, -(y0 + depth)),
        "bottom": (0.0, H + depth - y1),
        "left": (-(x0 + depth), 0.0),
        "right": (W + depth - x1, 0.0),
    }[edge]


def _edge_line_runs(sil, edge: str, depths: np.ndarray, bb, W: int, H: int) -> np.ndarray:
    """Longest subject run on the canvas edge row/column for each candidate depth, evaluated on
    the unshifted silhouette at the points that would land on that edge."""
    x0, y0, x1, y1 = bb
    if edge in ("top", "bottom"):
        xs = (np.arange(W) + 0.5)[None, :]
        ys = (y0 + depths + 0.5 if edge == "top" else y1 - depths - 0.5)[:, None]
    else:
        ys = (np.arange(H) + 0.5)[None, :]
        xs = (x0 + depths + 0.5 if edge == "left" else x1 - depths - 0.5)[:, None]
    xs, ys = np.broadcast_arrays(xs, ys)
    return longest_runs(alpha_u8(sil.sdf(xs, ys, None)) >= SUBJECT_ALPHA)


def edge_crop(item: PlanItem, rng: np.random.Generator, ctx: Context) -> Planted:
    """Push the base over one canvas edge until the longest run of subject pixels on that edge
    lands in the case's target range. Edges across the bbox's short axis are tried first, so the
    crop leaves the long side (and so the PPI) whole. A base that cannot reach the range on any
    edge (e.g. a flat side always touches with a long run) is swapped for the next base."""
    case = item.param["case"]
    lo, hi = EDGE_CASES[case]
    base = ctx.base(item.bases[0] + ctx.attempt)
    pl = base.placement
    sil = base.silhouette.mapped(pl.scale, pl.ox, pl.oy)
    bb = bbox(sil)
    bw, bh = bb[2] - bb[0], bb[3] - bb[1]
    ppi_est = max(bw, bh) / ctx.printable_in
    across_short = ["top", "bottom"] if bw >= bh else ["left", "right"]
    across_long = ["left", "right"] if bw >= bh else ["top", "bottom"]
    edges = list(rng.permutation(across_short)) + list(rng.permutation(across_long))
    for edge in edges:
        extent = bh if edge in ("top", "bottom") else bw
        # Depth -0.5 puts the bbox extreme on the edge pixels' centres; a touch can be shallower
        # than a pixel, so case (a) searches finely from there.
        if case == "a":
            depths = np.arange(-0.5, 40.0, 0.0625)[1:]
        else:
            depths = np.arange(0.0, 0.45 * extent, 0.5)
        runs_in = _edge_line_runs(sil, edge, depths, bb, pl.width, pl.height) / ppi_est
        ok = np.nonzero((runs_in >= lo) & (runs_in <= hi))[0]
        if ok.size:
            depth = float(depths[int(rng.choice(ok))])
            break
    else:
        raise Resample(f"base {base.index} cannot reach an edge run of {lo}-{hi} in on any edge")
    dx, dy = _shift(edge, depth, bb, pl.width, pl.height)
    r = render(base, replace(pl, ox=pl.ox + dx, oy=pl.oy + dy))
    mask = subject_of(r.rgba)
    if measure.label(mask, connectivity=1, return_num=True)[1] != 1:  # 4-connectivity, strictest
        raise Resample("the crop splits the subject")
    param = {**item.param, "edge": edge, "depth_px": depth, "target_run_in": [lo, hi]}
    return Planted(r.rgba, mask, False, [base.index], base.kind, param, _text_gt(r), None)


def text(item: PlanItem, rng: np.random.Generator, ctx: Context) -> Planted:
    """A badge with the planned word: correct, deliberately misspelled, or set at a given cap
    height in points at this sample's PPI (font size from the font's cap-height metric)."""
    base = ctx.base(item.bases[0])
    pl = base.placement
    ppi = base.long_px() / ctx.printable_in
    param = dict(item.param)
    cap_px = None
    if param.get("cap_pt") is not None:
        cap_px = txt.pt_to_px(param["cap_pt"], ppi)
        planned = param["word"]
        while not text_fits(base, pl, param["word"], cap_px):  # too wide: a shorter correct word
            shorter = [w for w in txt.WORDS if len(w) < len(param["word"])]
            if not shorter:
                raise Resample(f"no word fits the badge at {param['cap_pt']} pt")
            param["word"] = param["intended"] = shorter[int(rng.integers(len(shorter)))]
        if param["word"] != planned:
            param["planned_word"] = planned
    r = render(base, pl, word=param["word"], cap_px=cap_px)
    gt = {"garbled": param["variant"] == "garbled", "intended": param["intended"]}
    return _planted(r, base, item, gt, param)


BUILDERS: dict[str, Callable[[PlanItem, np.random.Generator, Context], Planted]] = {
    "clean": clean,
    "resolution": resolution,
    "background": background,
    "islands": islands,
    "soft_alpha": soft_alpha,
    "edge_crop": edge_crop,
    "text": text,
}
