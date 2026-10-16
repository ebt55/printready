"""Exact signed distance functions for the benchmark's procedural art.

A shape is described in "art units" and mapped to pixels with `mapped(scale, ox, oy)`
(pixel = art * scale + offset). `sdf(x, y, cache)` is negative inside and positive outside. Outside
a shape every primitive here returns the exact Euclidean distance to it, and so does a union (the
minimum of exact distances). That is what keeps the benchmark's ground truth closed-form:

- alpha = clip(0.5 - d, 0, 1) is a one-pixel anti-aliased edge everywhere;
- a ramp over 0 < d < W is a linear alpha ramp exactly W pixels wide;
- `support(ux, uy)` gives the shape's extent along a unit direction and a point that reaches it,
  so bounding boxes and the facing points of two parts (the islands gap) are analytic.

Pixel (col i, row j) has its centre at (i + 0.5, j + 0.5); the canvas spans [0, W] x [0, H].
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np

Cache = dict


class Shape(Protocol):
    def sdf(self, x: np.ndarray, y: np.ndarray, cache: Cache) -> np.ndarray: ...
    def mapped(self, s: float, ox: float, oy: float) -> Shape: ...


def alpha_u8(d: np.ndarray) -> np.ndarray:
    """8-bit alpha of a one-pixel anti-aliased edge at signed distance d (pixels)."""
    return np.floor(255.0 * np.clip(0.5 - d, 0.0, 1.0) + 0.5).astype(np.uint8)


def coverage(d: np.ndarray) -> np.ndarray:
    """Float coverage in [0, 1] of a region whose signed distance is d (pixels)."""
    return np.clip(0.5 - d, 0.0, 1.0)


def _cached(shape, x, y, cache: Cache, fn):
    # A render evaluates shapes on sub-windows of one pixel grid; the first sample point and the
    # shape of the window identify the window.
    key = (shape, x.shape, float(x.flat[0]), float(y.flat[0]))
    if cache is not None and key in cache:
        return cache[key]
    value = fn()
    if cache is not None:
        cache[key] = value
    return value


def _segment_distance(px, py, ax, ay, bx, by):
    ex, ey = bx - ax, by - ay
    wx, wy = px - ax, py - ay
    denom = ex * ex + ey * ey
    if denom == 0:
        return np.hypot(wx, wy)
    h = np.clip((wx * ex + wy * ey) / denom, 0.0, 1.0)
    return np.hypot(wx - ex * h, wy - ey * h)


# --- primitives (usable as silhouette parts: they have exact sdf and support) ------------------


@dataclass(frozen=True)
class Circle:
    cx: float
    cy: float
    r: float

    def sdf(self, x, y, cache=None):
        return _cached(self, x, y, cache, lambda: np.hypot(x - self.cx, y - self.cy) - self.r)

    def mapped(self, s, ox, oy):
        return Circle(self.cx * s + ox, self.cy * s + oy, self.r * s)

    def support(self, ux, uy):
        return (self.cx * ux + self.cy * uy + self.r, self.cx + self.r * ux, self.cy + self.r * uy)


@dataclass(frozen=True)
class RoundBox:
    """Rectangle of half extents (hw, hh) with corner radius r, rotated by `angle` radians."""

    cx: float
    cy: float
    hw: float
    hh: float
    r: float
    angle: float = 0.0

    def sdf(self, x, y, cache=None):
        def compute():
            c, s = math.cos(self.angle), math.sin(self.angle)
            dx, dy = x - self.cx, y - self.cy
            lx, ly = dx * c + dy * s, -dx * s + dy * c
            qx = np.abs(lx) - (self.hw - self.r)
            qy = np.abs(ly) - (self.hh - self.r)
            outside = np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0))
            return outside + np.minimum(np.maximum(qx, qy), 0.0) - self.r

        return _cached(self, x, y, cache, compute)

    def mapped(self, s, ox, oy):
        return RoundBox(self.cx * s + ox, self.cy * s + oy, self.hw * s, self.hh * s, self.r * s, self.angle)

    def corner_centres(self) -> list[tuple[float, float]]:
        c, s = math.cos(self.angle), math.sin(self.angle)
        out = []
        for sx, sy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            lx, ly = sx * (self.hw - self.r), sy * (self.hh - self.r)
            out.append((self.cx + lx * c - ly * s, self.cy + lx * s + ly * c))
        return out

    def support(self, ux, uy):
        corners = self.corner_centres()
        dots = [px * ux + py * uy for px, py in corners]
        best = max(dots)
        tied = [p for p, d in zip(corners, dots) if d >= best - 1e-9 * (1 + abs(best))]
        px = sum(p[0] for p in tied) / len(tied)  # midpoint of a flat side when two corners tie
        py = sum(p[1] for p in tied) / len(tied)
        return (best + self.r, px + self.r * ux, py + self.r * uy)


@dataclass(frozen=True)
class Star:
    """Regular star: n tips at radius r_out, n valleys at r_in, first tip at `angle`, then grown
    outward by `rounding` (which rounds the tips). Exact sdf by folding into one sector."""

    cx: float
    cy: float
    n: int
    r_out: float
    r_in: float
    angle: float
    rounding: float = 0.0

    def sdf(self, x, y, cache=None):
        def compute():
            half = math.pi / self.n
            dx, dy = x - self.cx, y - self.cy
            t = np.mod(np.arctan2(dy, dx) - self.angle + half, 2.0 * half) - half
            phi = np.abs(t)
            rho = np.hypot(dx, dy)
            px, py = rho * np.cos(phi), rho * np.sin(phi)
            tx, ty = self.r_out, 0.0
            vx, vy = self.r_in * math.cos(half), self.r_in * math.sin(half)
            ex, ey = vx - tx, vy - ty
            wx, wy = px - tx, py - ty
            h = np.clip((wx * ex + wy * ey) / (ex * ex + ey * ey), 0.0, 1.0)
            dist = np.hypot(wx - ex * h, wy - ey * h)
            inside = (ex * wy - ey * wx) > 0.0
            return np.where(inside, -dist, dist) - self.rounding

        return _cached(self, x, y, cache, compute)

    def mapped(self, s, ox, oy):
        return Star(self.cx * s + ox, self.cy * s + oy, self.n, self.r_out * s, self.r_in * s,
                    self.angle, self.rounding * s)

    def tips(self) -> list[tuple[float, float]]:
        step = 2.0 * math.pi / self.n
        return [(self.cx + self.r_out * math.cos(self.angle + k * step),
                 self.cy + self.r_out * math.sin(self.angle + k * step)) for k in range(self.n)]

    def support(self, ux, uy):
        # The tips are the convex hull as long as r_in < r_out * cos(pi / n), which the bases keep.
        tip = max(self.tips(), key=lambda p: p[0] * ux + p[1] * uy)
        return (tip[0] * ux + tip[1] * uy + self.rounding, tip[0] + self.rounding * ux,
                tip[1] + self.rounding * uy)


@dataclass(frozen=True)
class Capsule:
    ax: float
    ay: float
    bx: float
    by: float
    r: float

    def sdf(self, x, y, cache=None):
        return _cached(self, x, y, cache,
                       lambda: _segment_distance(x, y, self.ax, self.ay, self.bx, self.by) - self.r)

    def mapped(self, s, ox, oy):
        return Capsule(self.ax * s + ox, self.ay * s + oy, self.bx * s + ox, self.by * s + oy, self.r * s)

    def support(self, ux, uy):
        da, db = self.ax * ux + self.ay * uy, self.bx * ux + self.by * uy
        px, py = (self.ax, self.ay) if da >= db else (self.bx, self.by)
        return (max(da, db) + self.r, px + self.r * ux, py + self.r * uy)


@dataclass(frozen=True)
class Union:
    parts: tuple

    def sdf(self, x, y, cache=None):
        return _cached(self, x, y, cache,
                       lambda: np.minimum.reduce([p.sdf(x, y, cache) for p in self.parts]))

    def mapped(self, s, ox, oy):
        return Union(tuple(p.mapped(s, ox, oy) for p in self.parts))

    def support(self, ux, uy):
        return max((p.support(ux, uy) for p in self.parts), key=lambda t: t[0])


def bbox(shape) -> tuple[float, float, float, float]:
    """Analytic bounding box (x0, y0, x1, y1) of a shape that has `support`."""
    return (-shape.support(-1.0, 0.0)[0], -shape.support(0.0, -1.0)[0],
            shape.support(1.0, 0.0)[0], shape.support(0.0, 1.0)[0])


# --- paint-only regions (interior decoration; no support needed) -------------------------------


@dataclass(frozen=True)
class Arc:
    """Arc of radius `radius` around (cx, cy), `aperture` radians either side of straight down
    (+y in image coordinates, so it reads as a smile), stroked with half-thickness `half`."""

    cx: float
    cy: float
    radius: float
    aperture: float
    half: float

    def sdf(self, x, y, cache=None):
        sx, sy = math.sin(self.aperture), math.cos(self.aperture)
        px, py = np.abs(x - self.cx), y - self.cy
        to_end = np.hypot(px - sx * self.radius, py - sy * self.radius)
        to_ring = np.abs(np.hypot(px, py) - self.radius)
        return np.where(sy * px > sx * py, to_end, to_ring) - self.half

    def mapped(self, s, ox, oy):
        return Arc(self.cx * s + ox, self.cy * s + oy, self.radius * s, self.aperture, self.half * s)


@dataclass(frozen=True)
class Inset:
    """The shape shrunk by d (grown when d < 0)."""

    shape: object
    d: float

    def sdf(self, x, y, cache=None):
        return self.shape.sdf(x, y, cache) + self.d

    def mapped(self, s, ox, oy):
        return Inset(self.shape.mapped(s, ox, oy), self.d * s)


@dataclass(frozen=True)
class Shell:
    """A band `width` wide that starts `inset` inside the shape's boundary (a ring or outline)."""

    shape: object
    inset: float
    width: float

    def sdf(self, x, y, cache=None):
        return np.abs(self.shape.sdf(x, y, cache) + self.inset + self.width / 2.0) - self.width / 2.0

    def mapped(self, s, ox, oy):
        return Shell(self.shape.mapped(s, ox, oy), self.inset * s, self.width * s)


def region_bbox(region) -> tuple[float, float, float, float]:
    """A box that contains every point where `region`'s sdf is negative (paint regions included)."""
    if isinstance(region, Inset):
        grow = max(0.0, -region.d)
        x0, y0, x1, y1 = region_bbox(region.shape)
    elif isinstance(region, Shell):
        grow = max(0.0, -region.inset)
        x0, y0, x1, y1 = region_bbox(region.shape)
    elif isinstance(region, Arc):
        r = region.radius + region.half
        return (region.cx - r, region.cy - r, region.cx + r, region.cy + r)
    else:
        return bbox(region)
    return (x0 - grow, y0 - grow, x1 + grow, y1 + grow)
