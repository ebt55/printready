"""Procedural base art: 40 clean sticker designs per split, rendered from exact signed distances.

Kinds: outlined blob characters with eyes, round and rounded-rect badges with a ring and one
correctly spelled word, stars, bursts, and overlapping multi-part compositions that form one
component. A base is a description (shapes, colours, word) plus a native placement on its canvas;
the defect families re-render it at other scales, positions or with a glow.

Every base is clean by construction:
- one component: every part overlaps the main part's interior, and no part encloses a hole;
- anti-aliased edge one pixel wide (alpha = clip(0.5 - d, 0, 1) of an exact distance);
- margin of at least 8 % of the canvas on every side;
- subject bbox long side 940-1000 px, so PPI at a 3 in order is 335.7-357.1 (>= 330).
"""

from __future__ import annotations

import colorsys
import math
from dataclasses import dataclass, replace

import numpy as np
from PIL import Image, ImageDraw

from printready.bench import text as txt
from printready.bench.shapes import (
    Arc,
    Capsule,
    Circle,
    Inset,
    RoundBox,
    Shell,
    Star,
    Union,
    bbox,
    coverage,
    region_bbox,
)

RGB = tuple[int, int, int]

KINDS: tuple[str, ...] = ("blob", "badge_round", "star", "composite", "badge_rrect", "burst")
BADGE_KINDS: tuple[str, ...] = ("badge_round", "badge_rrect")
N_BASES = 40
CANVAS_LONG = 1200
CANVAS_SHORT = 960  # the short side of the landscape / portrait canvases
MARGIN_FRAC = 0.08
MARGIN_SAFETY_PX = 2.0  # the anti-aliased half pixel and rounding never eat into the 8 %
BASE_LONG_PX = (940.0, 1000.0)
BASE_STREAM = 0  # seed stream id for base designs (families use their own ids)

WHITE: RGB = (255, 255, 255)
CREAM: RGB = (250, 244, 228)
NEAR_BLACKS: tuple[RGB, ...] = ((32, 28, 38), (24, 32, 56), (52, 26, 30), (22, 44, 40), (40, 40, 40))


# --- colour helpers ---------------------------------------------------------------------------


def hsv(h: float, s: float, v: float) -> RGB:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, s, v)
    return (round(r * 255), round(g * 255), round(b * 255))


def mix(a: RGB, b: RGB, t: float) -> RGB:
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))  # type: ignore[return-value]


def shade(c: RGB, f: float) -> RGB:
    return tuple(round(x * f) for x in c)  # type: ignore[return-value]


def luma(c: RGB) -> float:
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


def _outline(rng: np.random.Generator, fill: RGB) -> RGB:
    """A dark outline colour: a near-black or a deep shade of the fill (luma always below 75)."""
    if rng.random() < 0.5:
        return NEAR_BLACKS[int(rng.integers(len(NEAR_BLACKS)))]
    return shade(fill, 0.28)


def _text_colour(fill: RGB, outline: RGB) -> RGB:
    return CREAM if luma(fill) < 150 else outline


# --- the description of a base ----------------------------------------------------------------


@dataclass(frozen=True)
class Paint:
    """One colour layer. `region` is any shape with an sdf; with `rim` > 0 the layer is instead the
    outer band of the silhouette, `rim` art units wide (the outline that every edge pixel shows)."""

    color: RGB
    region: object | None = None
    rim: float = 0.0


@dataclass(frozen=True)
class TextSpec:
    word: str
    cx: float
    cy: float  # the word's cap height is centred on (cx, cy)
    cap: float  # default cap height, art units
    max_width: float  # widest the word's ink may be, art units
    color: RGB


@dataclass(frozen=True)
class Placement:
    """Art -> pixel transform (pixel = art * scale + offset) and the canvas size."""

    scale: float
    ox: float
    oy: float
    width: int
    height: int


@dataclass(frozen=True)
class Base:
    index: int
    kind: str
    silhouette: Union
    fill: RGB
    paints: tuple[Paint, ...]
    edge_color: RGB  # the colour every boundary pixel of the subject shows (the rim)
    text: TextSpec | None
    placement: Placement

    def bbox_px(self, placement: Placement | None = None) -> tuple[float, float, float, float]:
        pl = placement or self.placement
        return bbox(self.silhouette.mapped(pl.scale, pl.ox, pl.oy))

    def long_px(self, placement: Placement | None = None) -> float:
        x0, y0, x1, y1 = self.bbox_px(placement)
        return max(x1 - x0, y1 - y0)


# --- kind builders: each returns (silhouette, fill, paints, edge_color, text) ------------------


def _blob(rng: np.random.Generator):
    R = 300.0
    parts = [Circle(0.0, 0.0, R)]
    n_lobes = int(rng.integers(2, 5))
    a0 = rng.uniform(0, 2 * math.pi)
    for k in range(n_lobes):
        a = a0 + 2 * math.pi * k / n_lobes + rng.uniform(-0.35, 0.35)
        dist, r = rng.uniform(0.3, 0.55) * R, rng.uniform(0.5, 0.72) * R
        parts.append(Circle(dist * math.cos(a), dist * math.sin(a), r))
    if rng.random() < 0.6:  # feet
        spread, rf = rng.uniform(0.45, 0.7), rng.uniform(0.2, 0.28) * R
        for sgn in (-1, 1):
            a = math.pi / 2 + sgn * spread
            parts.append(Circle(0.88 * R * math.cos(a), 0.88 * R * math.sin(a), rf))
    if rng.random() < 0.45:  # ears
        spread, re = rng.uniform(0.5, 0.8), rng.uniform(0.18, 0.26) * R
        for sgn in (-1, 1):
            a = -math.pi / 2 + sgn * spread
            parts.append(Circle(0.9 * R * math.cos(a), 0.9 * R * math.sin(a), re))
    sil = Union(tuple(parts))
    fill = hsv(rng.uniform(), rng.uniform(0.45, 0.8), rng.uniform(0.8, 0.97))
    outline = _outline(rng, fill)
    x0, y0, x1, y1 = bbox(sil)
    rim = rng.uniform(0.024, 0.032) * max(x1 - x0, y1 - y0)

    paints: list[Paint] = []
    if rng.random() < 0.5:  # belly
        paints.append(Paint(mix(fill, WHITE, 0.45), Circle(0.0, 0.42 * R, 0.42 * R)))
    if rng.random() < 0.5:  # cheeks
        pink = mix(fill, (240, 120, 150), 0.6)
        for sgn in (-1, 1):
            paints.append(Paint(pink, Circle(sgn * 0.52 * R, 0.14 * R, 0.09 * R)))
    er = rng.uniform(0.13, 0.17) * R
    ex, ey = rng.uniform(0.28, 0.36) * R, -rng.uniform(0.08, 0.18) * R
    gx, gy = rng.uniform(-0.25, 0.25, size=2) * er
    for sgn in (-1, 1):
        eye = Circle(sgn * ex, ey, er)
        paints += [
            Paint(WHITE, eye),
            Paint(outline, Shell(eye, 0.0, 0.18 * er)),
            Paint(outline, Circle(sgn * ex + gx, ey + gy, 0.5 * er)),
            Paint(WHITE, Circle(sgn * ex + gx - 0.18 * er, ey + gy - 0.18 * er, 0.15 * er)),
        ]
    paints.append(Paint(outline, Arc(0.0, ey + 0.02 * R, 0.2 * R, rng.uniform(0.6, 1.0), 0.025 * R)))
    paints.append(Paint(outline, rim=rim))
    return sil, fill, paints, outline, None


def _badge_round(rng: np.random.Generator):
    R = 500.0
    disc = Circle(0.0, 0.0, R)
    fill = hsv(rng.uniform(), rng.uniform(0.55, 0.85), rng.uniform(0.62, 0.9))
    outline = _outline(rng, fill)
    ring = CREAM if rng.random() < 0.5 else WHITE
    rim = rng.uniform(0.024, 0.032) * 2 * R
    paints = [
        Paint(ring, Shell(disc, 0.1 * R, 0.03 * R)),
        Paint(ring, Star(0.0, -0.56 * R, 5, 0.09 * R, 0.04 * R, -math.pi / 2, 0.005 * R)),
        Paint(ring, Capsule(-0.22 * R, 0.56 * R, 0.22 * R, 0.56 * R, 0.022 * R)),
        Paint(outline, rim=rim),
    ]
    word = txt.WORDS[int(rng.integers(len(txt.WORDS)))]
    text = TextSpec(word, 0.0, 0.0, rng.uniform(0.15, 0.2) * R, 1.35 * R, _text_colour(fill, outline))
    return Union((disc,)), fill, paints, outline, text


def _badge_rrect(rng: np.random.Generator):
    hw = 500.0
    hh = hw / rng.uniform(1.4, 1.9)
    box = RoundBox(0.0, 0.0, hw, hh, rng.uniform(0.3, 1.0) * hh)
    fill = hsv(rng.uniform(), rng.uniform(0.55, 0.85), rng.uniform(0.62, 0.9))
    outline = _outline(rng, fill)
    ring = CREAM if rng.random() < 0.5 else WHITE
    rim = rng.uniform(0.024, 0.032) * 2 * hw
    dot_x = hw - 0.42 * hh
    paints = [
        Paint(ring, Shell(box, 0.12 * hh, 0.04 * hh)),
        Paint(ring, Circle(-dot_x, 0.0, 0.08 * hh)),
        Paint(ring, Circle(dot_x, 0.0, 0.08 * hh)),
        Paint(outline, rim=rim),
    ]
    word = txt.WORDS[int(rng.integers(len(txt.WORDS)))]
    text = TextSpec(word, 0.0, 0.0, rng.uniform(0.3, 0.38) * hh, 2 * (hw - 0.6 * hh),
                    _text_colour(fill, outline))
    return Union((box,)), fill, paints, outline, text


def _star(rng: np.random.Generator):
    R = 500.0
    n = int(rng.integers(5, 9))
    star = Star(0.0, 0.0, n, R, rng.uniform(0.46, 0.58) * R, -math.pi / 2 + rng.uniform(-0.2, 0.2),
                rng.uniform(0.03, 0.06) * R)
    hue = float(rng.choice([0.13, 0.08, 0.95, 0.55, 0.33])) + rng.uniform(-0.03, 0.03)
    fill = hsv(hue, rng.uniform(0.6, 0.9), rng.uniform(0.85, 0.98))
    outline = _outline(rng, fill)
    x0, y0, x1, y1 = bbox(star)
    rim = rng.uniform(0.024, 0.032) * max(x1 - x0, y1 - y0)
    paints = [Paint(mix(fill, WHITE, 0.35), Inset(star, 0.13 * R))]
    if rng.random() < 0.6:  # a face
        for sgn in (-1, 1):
            paints.append(Paint(outline, Circle(sgn * 0.12 * R, -0.04 * R, 0.045 * R)))
        paints.append(Paint(outline, Arc(0.0, -0.02 * R, 0.1 * R, 0.9, 0.018 * R)))
    else:
        accent = hsv(hue + 0.5, 0.7, 0.85)
        centre = Circle(0.0, 0.0, 0.16 * R)
        paints += [Paint(accent, centre), Paint(outline, Shell(centre, 0.0, 0.02 * R))]
    paints.append(Paint(outline, rim=rim))
    return Union((star,)), fill, paints, outline, None


def _burst(rng: np.random.Generator):
    R = 500.0
    n = int(rng.integers(14, 27))
    burst = Star(0.0, 0.0, n, R, rng.uniform(0.8, 0.88) * R, rng.uniform(0, 2 * math.pi), 0.012 * R)
    hue = rng.uniform()
    fill = hsv(hue, rng.uniform(0.6, 0.9), rng.uniform(0.8, 0.97))
    outline = _outline(rng, fill)
    x0, y0, x1, y1 = bbox(burst)
    rim = rng.uniform(0.024, 0.032) * max(x1 - x0, y1 - y0)
    inner = Circle(0.0, 0.0, 0.64 * R)
    paints = [
        Paint(hsv(hue + 0.5, 0.65, 0.8), inner),
        Paint(WHITE, Shell(inner, 0.04 * R, 0.03 * R)),
        Paint(mix(fill, WHITE, 0.3), Star(0.0, 0.0, 5, 0.3 * R, 0.13 * R, -math.pi / 2, 0.01 * R)),
        Paint(outline, rim=rim),
    ]
    return Union((burst,)), fill, paints, outline, None


def _composite(rng: np.random.Generator):
    """Two to three overlapping parts. Every satellite's centre lies inside the main part, so the
    union is one component; satellites sit far enough apart that no hole can close."""
    template = int(rng.integers(3))
    fill = hsv(rng.uniform(), rng.uniform(0.5, 0.8), rng.uniform(0.7, 0.95))
    outline = _outline(rng, fill)
    light = mix(fill, WHITE, 0.6)
    sats: list[object] = []
    main_paints: list[Paint] = []
    if template == 0:  # disc with one or two stars over its upper rim
        R = 380.0
        main = Circle(0.0, 0.0, R)
        main_paints.append(Paint(light, Shell(main, 0.1 * R, 0.03 * R)))
        if rng.random() < 0.5:
            angles = [-3 * math.pi / 4, -math.pi / 4]
        else:
            angles = [float(rng.choice([-3 * math.pi / 4, -math.pi / 2, -math.pi / 4]))]
        for a in angles:
            a += rng.uniform(-0.2, 0.2)
            rs = rng.uniform(0.42, 0.55) * R
            sats.append(Star(0.92 * R * math.cos(a), 0.92 * R * math.sin(a), 5, rs, 0.5 * rs,
                             -math.pi / 2 + rng.uniform(-0.3, 0.3), 0.05 * rs))
    elif template == 1:  # badge with a banner across its lower half (and maybe a star on top)
        if rng.random() < 0.5:
            main = Circle(0.0, 0.0, 400.0)
        else:
            main = RoundBox(0.0, 0.0, 380.0, 340.0, rng.uniform(80, 160))
        main_paints.append(Paint(light, Inset(main, 0.12 * 400.0)))
        yb = rng.uniform(0.3, 0.45) * 400.0
        half = rng.uniform(1.15, 1.35) * 400.0
        sats.append(Capsule(-half, yb, half, yb, rng.uniform(70, 95)))
        if rng.random() < 0.5:
            sats.append(Star(0.0, -310.0, 5, 120.0, 55.0, -math.pi / 2, 6.0))
    else:  # box with two bubbles on opposite corners
        hw, hh = 380.0, 300.0
        main = RoundBox(0.0, 0.0, hw, hh, rng.uniform(60, 120))
        main_paints.append(Paint(light, RoundBox(0.0, 0.0, 0.6 * hw, 0.5 * hh, 40.0)))
        sy = 1 if rng.random() < 0.5 else -1
        for sx in (-1, 1):
            sats.append(Circle(sx * 0.8 * hw, sx * sy * 0.8 * hh, rng.uniform(140, 200)))
    sil = Union((main, *sats))
    x0, y0, x1, y1 = bbox(sil)
    long_art = max(x1 - x0, y1 - y0)
    rim = rng.uniform(0.024, 0.032) * long_art
    paints = list(main_paints)
    for k, sat in enumerate(sats):
        sat_fill = hsv(rng.uniform(), rng.uniform(0.55, 0.85), rng.uniform(0.8, 0.97))
        paints += [Paint(sat_fill, sat), Paint(outline, Shell(sat, 0.0, 0.6 * rim))]
    paints.append(Paint(outline, rim=rim))
    return sil, fill, paints, outline, None


_BUILDERS = {
    "blob": _blob,
    "badge_round": _badge_round,
    "badge_rrect": _badge_rrect,
    "star": _star,
    "burst": _burst,
    "composite": _composite,
}


def _place(rng: np.random.Generator, sil: Union) -> Placement:
    x0, y0, x1, y1 = bbox(sil)
    bw, bh = x1 - x0, y1 - y0
    long_px = rng.uniform(*BASE_LONG_PX)
    s = long_px / max(bw, bh)
    width = height = CANVAS_LONG
    short_px = min(bw, bh) * s
    if short_px <= (1 - 2 * MARGIN_FRAC) * CANVAS_SHORT - 2 * MARGIN_SAFETY_PX - 4 and rng.random() < 0.35:
        if bw >= bh:
            height = CANVAS_SHORT
        else:
            width = CANVAS_SHORT
    mx = MARGIN_FRAC * width + MARGIN_SAFETY_PX
    my = MARGIN_FRAC * height + MARGIN_SAFETY_PX
    free_x, free_y = width - 2 * mx - bw * s, height - 2 * my - bh * s
    assert free_x >= 0 and free_y >= 0, "base does not fit its canvas with 8 % margins"
    left = mx + rng.uniform(0, free_x)
    top = my + rng.uniform(0, free_y)
    return Placement(s, left - x0 * s, top - y0 * s, width, height)


def base_kind(index: int) -> str:
    return KINDS[index % len(KINDS)]


def badge_indices() -> list[int]:
    return [i for i in range(N_BASES) if base_kind(i) in BADGE_KINDS]


def make_base(seed: int, index: int) -> Base:
    """The index-th base design of a split. Deterministic in (seed, index)."""
    rng = np.random.default_rng(np.random.SeedSequence([seed, BASE_STREAM, index]))
    kind = base_kind(index)
    sil, fill, paints, edge, text = _BUILDERS[kind](rng)
    return Base(index, kind, sil, fill, tuple(paints), edge, text, _place(rng, sil))


# --- rendering --------------------------------------------------------------------------------


@dataclass
class Rendered:
    rgba: np.ndarray  # HxWx4 uint8, straight alpha, RGB zeroed where alpha is 0
    bbox: tuple[float, float, float, float]  # analytic pixel bbox of the silhouette
    word: str | None = None
    font_px: float | None = None
    cap_px: float | None = None  # cap height from the font's metrics at font_px


def default_cap_px(base: Base, placement: Placement, word: str) -> float:
    """The base's design cap height, shrunk if needed so the word fits its badge."""
    spec = base.text
    assert spec is not None
    cap = spec.cap * placement.scale
    size = txt.font_size_for_cap(cap)
    width = txt.ink_width(word, size)
    limit = spec.max_width * placement.scale
    if width > limit:
        size = txt.font_size_for_cap(cap * limit / width * 0.995)
    return size * txt.cap_ratio()


def text_fits(base: Base, placement: Placement, word: str, cap_px: float) -> bool:
    spec = base.text
    assert spec is not None
    return txt.ink_width(word, txt.font_size_for_cap(cap_px)) <= spec.max_width * placement.scale


def _blend(rgb: np.ndarray, color: RGB, cov: np.ndarray) -> None:
    rgb += (np.asarray(color, dtype=np.float64) - rgb) * cov[..., None]


def render(
    base: Base,
    placement: Placement | None = None,
    *,
    word: str | None = None,
    cap_px: float | None = None,
    glow: tuple[int, RGB] | None = None,
) -> Rendered:
    """Render a base. `word`/`cap_px` override a badge's text; `glow=(width_px, colour)` replaces
    the one-pixel edge with a linear alpha ramp exactly `width_px` wide outside the silhouette."""
    pl = placement or base.placement
    s, ox, oy, W, H = pl.scale, pl.ox, pl.oy, pl.width, pl.height
    sil = base.silhouette.mapped(s, ox, oy)
    x0, y0, x1, y1 = bbox(sil)
    rgba = np.zeros((H, W, 4), dtype=np.uint8)
    pad = 2.0 + (glow[0] if glow else 0)
    wx0, wx1 = max(0, math.floor(x0 - pad)), min(W, math.ceil(x1 + pad))
    wy0, wy1 = max(0, math.floor(y0 - pad)), min(H, math.ceil(y1 + pad))
    result = Rendered(rgba, (x0, y0, x1, y1))
    if wx1 <= wx0 or wy1 <= wy0:
        return result

    X, Y = np.meshgrid(np.arange(wx0, wx1) + 0.5, np.arange(wy0, wy1) + 0.5)
    cache: dict = {}
    d = sil.sdf(X, Y, cache)
    rgb = np.empty(X.shape + (3,), dtype=np.float64)
    rgb[...] = base.fill
    for paint in base.paints:
        if paint.rim > 0:
            _blend(rgb, paint.color, np.clip(0.5 + d + paint.rim * s, 0.0, 1.0))
            continue
        # Coverage is exactly 0 more than half a pixel outside a region, so each layer is only
        # evaluated and blended inside its own box (same bytes, much less work).
        region = paint.region.mapped(s, ox, oy)
        rx0, ry0, rx1, ry1 = region_bbox(region)
        sx0, sx1 = max(wx0, math.floor(rx0 - 1)), min(wx1, math.ceil(rx1 + 1))
        sy0, sy1 = max(wy0, math.floor(ry0 - 1)), min(wy1, math.ceil(ry1 + 1))
        if sx1 <= sx0 or sy1 <= sy0:
            continue
        win = (slice(sy0 - wy0, sy1 - wy0), slice(sx0 - wx0, sx1 - wx0))
        _blend(rgb[win], paint.color, coverage(region.sdf(X[win], Y[win], cache)))

    if base.text is not None:
        spec = base.text
        word = word or spec.word
        cap = cap_px if cap_px is not None else default_cap_px(base, pl, word)
        size = txt.font_size_for_cap(cap)
        cap_actual = size * txt.cap_ratio()
        layer = Image.new("L", (wx1 - wx0, wy1 - wy0), 0)
        draw = ImageDraw.Draw(layer)
        cx = spec.cx * s + ox - wx0
        baseline = spec.cy * s + oy - wy0 + cap_actual / 2.0
        draw.text((cx, baseline), word, fill=255, font=txt.font(size), anchor="ms")
        box = layer.getbbox()
        if box is not None:
            win = (slice(box[1], box[3]), slice(box[0], box[2]))
            _blend(rgb[win], spec.color, np.asarray(layer.crop(box), dtype=np.float64) / 255.0)
        result.word, result.font_px, result.cap_px = word, size, cap_actual

    if glow is not None:
        width_px, glow_color = glow
        art = coverage(d)[..., None]
        rgb = rgb * art + np.asarray(glow_color, dtype=np.float64) * (1.0 - art)
        alpha = np.where(d <= 0.0, 1.0, np.clip(1.0 - d / width_px, 0.0, 1.0))
    else:
        alpha = coverage(d)

    a8 = np.floor(alpha * 255.0 + 0.5).astype(np.uint8)
    rgb8 = np.floor(np.clip(rgb, 0.0, 255.0) + 0.5).astype(np.uint8)
    rgb8[a8 == 0] = 0
    rgba[wy0:wy1, wx0:wx1, :3] = rgb8
    rgba[wy0:wy1, wx0:wx1, 3] = a8
    return result


def scaled_placement(base: Base, long_px: float) -> Placement:
    """The native placement scaled so the subject bbox long side is `long_px` (canvas scales too)."""
    pl = base.placement
    k = long_px / base.long_px()
    return replace(pl, scale=pl.scale * k, ox=pl.ox * k, oy=pl.oy * k,
                   width=round(pl.width * k), height=round(pl.height * k))
