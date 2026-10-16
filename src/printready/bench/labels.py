"""Expected labels from ground-truth quantities, the 10 % rule, and the expected outcome.

Nothing here looks at pixels. Every label is a comparison of a ground-truth quantity that the
generator planted or measured on its own drawing (PPI from the subject bbox, the gap between two
parts, the width of an alpha ramp, the longest run of subject pixels on a canvas edge, the ring's
colour spread, a cap height from font metrics) against a threshold read from the profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from printready.profile import Profile
from printready.types import (
    DETERMINISTIC_CHECK_IDS,
    VISION_CHECK_IDS,
    Artwork,
    Finding,
    Report,
    Step,
    outcome,
)

BAND = 0.10  # no label-deciding quantity may sit within 10 % of its threshold
MIN_SIDE_PX = 64  # `file` check: at least 64 px a side (01-DESIGN, deterministic checks)
MASK_CHECKS = ("soft_alpha", "edge_crop", "islands")  # need a subject; skip while opaque
AUTO_FIX = {"background": "remove_background", "edge_crop": "pad_canvas", "islands": "bridge_islands"}
SHAPE_FIX = "fit_shape"  # a background a person would have to cut out: whole-image rounded rectangle

Label = dict[str, str]  # {"status": ..., "fixer": ...}


@dataclass(frozen=True)
class Thresholds:
    """The profile values that decide a benchmark label, in one place."""

    ppi_target: float
    ppi_floor: float
    border_in: float
    max_bridge_border_in: float
    soft_alpha_max_in: float
    edge_cut_min_run_in: float
    bg_delta_e: float
    bg_ring_uniform_frac: float
    min_text_pt: float
    cap_height_ratio: float
    max_upload_bytes: int
    bleed_in: float

    @classmethod
    def from_profile(cls, p: Profile) -> Thresholds:
        return cls(
            ppi_target=p.ppi_target,
            ppi_floor=p.ppi_floor,
            border_in=p.border_in,
            max_bridge_border_in=p.max_bridge_border_in,
            soft_alpha_max_in=p.soft_alpha_max_in,
            edge_cut_min_run_in=p.edge_cut_min_run_in,
            bg_delta_e=p.bg_delta_e,
            bg_ring_uniform_frac=p.bg_ring_uniform_frac,
            min_text_pt=p.min_text_pt,
            cap_height_ratio=p.cap_height_ratio,
            max_upload_bytes=p.max_upload_bytes,
            bleed_in=p.bleed_in,
        )

    def shape_in(self, size_in: float) -> float:
        """The PPI denominator for a whole-image rounded-rectangle sticker (fit_shape): the canvas
        long side spans the order size plus the bleed on both sides."""
        return size_in + 2 * self.bleed_in

    def printable_in(self, size_in: float) -> float:
        """The art's long side at an order of `size_in`: the contract's PPI denominator."""
        return size_in - 2 * self.border_in

    @property
    def merge_gap_in(self) -> float:
        """Parts closer than this merge under the standard border (dilation by border_in)."""
        return 2 * self.border_in

    @property
    def bridge_gap_in(self) -> float:
        """Parts closer than this join at the largest border we grow to (max_bridge_border_in)."""
        return 2 * self.max_bridge_border_in

    @property
    def small_text_pt(self) -> float:
        return self.cap_height_ratio * self.min_text_pt


def _label(status: str, fixer: str = "none") -> Label:
    return {"status": status, "fixer": fixer}


def resolution_label(ppi: float, ppi_at_1in: float, th: Thresholds) -> Label:
    if ppi >= th.ppi_target:
        return _label("pass")
    if ppi >= th.ppi_floor:
        return _label("warn", "customer")  # sharp at a smaller size
    # Below the floor: a smaller size fixes it unless even a 1 in sticker is below the floor.
    return _label("fail", "customer" if ppi_at_1in >= th.ppi_floor else "person")


def labels(gt: dict[str, Any], th: Thresholds, *, vision: bool = False) -> dict[str, Label]:
    """Expected status and fixer of every check on the image as generated (what run_checks
    should report on load). Pass and skip carry fixer "none"."""
    out: dict[str, Label] = {}
    ok_file = gt["min_side_px"] >= MIN_SIDE_PX and gt["file_bytes"] <= th.max_upload_bytes
    out["file"] = _label("pass") if ok_file else _label("fail", "customer")
    out["resolution"] = resolution_label(gt["ppi"], gt["ppi_at_1in"], th)
    if gt["opaque"]:
        uniform = gt["ring_uniformity"] >= th.bg_ring_uniform_frac
        out["background"] = _label("fail", "auto" if uniform else "person")
        for check in MASK_CHECKS:
            out[check] = _label("skip")
    else:
        out["background"] = _label("pass")
        out["soft_alpha"] = (_label("warn", "person") if gt["ramp_in"] > th.soft_alpha_max_in
                             else _label("pass"))
        run = gt["edge_run_in"]
        if gt["edge_run_px"] == 0:
            out["edge_crop"] = _label("pass")
        elif run <= th.edge_cut_min_run_in:
            out["edge_crop"] = _label("warn", "auto")
        else:
            out["edge_crop"] = _label("fail", "person")
        if gt["parts"] == 1 or gt["gap_in"] < th.merge_gap_in:
            out["islands"] = _label("pass")
        elif gt["gap_in"] <= th.bridge_gap_in:
            out["islands"] = _label("fail", "auto")
        else:
            out["islands"] = _label("fail", "person")
    missing = set(DETERMINISTIC_CHECK_IDS) - set(out)
    if missing:  # the contract grew a check this generator does not know how to label
        raise ValueError(f"no benchmark label for deterministic checks: {sorted(missing)}")
    if vision:
        garbled = bool(gt.get("garbled", False))
        out["text_garbled"] = _label("fail", "person") if garbled else _label("pass")
        small = gt.get("cap_height_pt") is not None and gt["cap_height_pt"] < th.small_text_pt
        out["text_small"] = _label("warn", "customer") if small else _label("pass")
    return {k: out[k] for k in (*DETERMINISTIC_CHECK_IDS, *(VISION_CHECK_IDS if vision else ()))}


def as_subject(gt: dict[str, Any]) -> dict[str, Any]:
    """The same ground truth once the subject is known (after a correct background removal)."""
    sub = dict(gt)
    sub["opaque"] = False
    sub["ppi"] = gt["ppi_subject"]
    sub["ppi_at_1in"] = gt["ppi_subject_at_1in"]
    return sub


def shape_labels(gt: dict[str, Any], th: Thresholds, *, vision: bool = False) -> dict[str, Label]:
    """Labels for the whole image as a rounded-rectangle sticker (after fit_shape, 01-DESIGN
    addendum "shape fallback"): the cut-out checks do not apply and pass, resolution is re-judged at
    the shape scale (canvas long side over size + 2 x bleed), and product_fit is a warn for the
    customer to accept the product change. Text checks are unchanged."""
    out = labels(gt, th, vision=vision)
    out["resolution"] = resolution_label(gt["ppi_shape"], gt["ppi_shape_at_1in"], th)
    for check in ("background", *MASK_CHECKS):
        out[check] = _label("pass")
    out["product_fit"] = _label("warn", "customer")
    return out


def expected_final(gt: dict[str, Any], th: Thresholds, *, vision: bool = False):
    """Labels after the rules pipeline does exactly what the planted defect calls for.

    Mirrors the design's fixed order: remove_background on a background fail/auto, or fit_shape on a
    background fail/person; then pad_canvas on an edge_crop warn/auto and bridge_islands on an
    islands fail/auto. Each fix is assumed to succeed without damage.
    Returns (final labels, names of the corrective fixes applied)."""
    current = labels(gt, th, vision=vision)
    applied: list[str] = []
    if current["background"] == _label("fail", "person"):
        return shape_labels(gt, th, vision=vision), [SHAPE_FIX]
    if current["background"] == _label("fail", "auto"):
        applied.append(AUTO_FIX["background"])
        current = labels(as_subject(gt), th, vision=vision)
    for check in ("edge_crop", "islands"):
        if current[check]["status"] in ("warn", "fail") and current[check]["fixer"] == "auto":
            applied.append(AUTO_FIX[check])
            current[check] = _label("pass")
    return current, applied


def expected_outcome(final: dict[str, Label], applied: list[str]) -> str:
    """The contract's outcome() on a synthetic final report and history."""
    art = Artwork(
        rgba=np.zeros((1, 1, 4), dtype=np.uint8),
        subject=None,
        ppi=1.0,
        history=[Step(fix=f, ok=True, damaged=False, note="planted defect fixed") for f in applied],
    )
    report = Report([Finding(check=c, status=v["status"], message="", measured={}, fixer=v["fixer"])
                     for c, v in final.items()])
    return outcome(art, report)


def near_threshold(gt: dict[str, Any], th: Thresholds) -> list[str]:
    """Every label-deciding quantity that sits within 10 % of its threshold (empty = fine)."""
    reasons: list[str] = []

    def check(name: str, value: float, threshold: float) -> None:
        if abs(value - threshold) < BAND * threshold:
            reasons.append(f"{name}={value:.4g} is within 10% of {threshold:g}")

    check("min_side_px", gt["min_side_px"], MIN_SIDE_PX)
    check("file_bytes", gt["file_bytes"], th.max_upload_bytes)
    for key in ("ppi", "ppi_subject"):
        check(key, gt[key], th.ppi_floor)
        check(key, gt[key], th.ppi_target)
        if gt[key] < th.ppi_floor:  # the fixer depends on whether a 1 in sticker clears the floor
            check(f"{key}_at_1in", gt[f"{key}_at_1in"], th.ppi_floor)
    # Mask quantities: decide the labels directly (alpha) or after background removal (opaque).
    check("ramp_in", gt["ramp_in"], th.soft_alpha_max_in)
    if gt["edge_run_px"] > 0:
        check("edge_run_in", gt["edge_run_in"], th.edge_cut_min_run_in)
    if gt["parts"] > 1:
        check("gap_in", gt["gap_in"], th.merge_gap_in)
        check("gap_in", gt["gap_in"], th.bridge_gap_in)
    if gt["opaque"]:
        if gt["ring_uniformity"] < th.bg_ring_uniform_frac:  # fit_shape re-judges PPI at shape scale
            check("ppi_shape", gt["ppi_shape"], th.ppi_floor)
            check("ppi_shape", gt["ppi_shape"], th.ppi_target)
            if gt["ppi_shape"] < th.ppi_floor:
                check("ppi_shape_at_1in", gt["ppi_shape_at_1in"], th.ppi_floor)
        if gt["ring_uniformity"] >= th.bg_ring_uniform_frac:
            # A fraction capped at 1 cannot sit 10 % above 0.95, so for a uniform ring the deciding
            # quantity is its colour spread: every ring pixel well inside bg_delta_e of the mean.
            if gt["ring_uniformity"] < 1.0:
                reasons.append(f"ring_uniformity={gt['ring_uniformity']:.4g} is not exactly 1")
            if gt["ring_de_max"] > (1 - BAND) * th.bg_delta_e:
                reasons.append(f"ring_de_max={gt['ring_de_max']:.3g} is within 10% of {th.bg_delta_e:g}")
        else:
            check("ring_uniformity", gt["ring_uniformity"], th.bg_ring_uniform_frac)
    if gt.get("cap_height_pt") is not None:
        check("cap_height_pt", gt["cap_height_pt"], th.small_text_pt)
    return reasons
