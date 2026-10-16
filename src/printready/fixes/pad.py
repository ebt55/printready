"""pad_canvas: transparent margin so any border up to max_bridge_border_in fits on the canvas."""

from __future__ import annotations

import math

import numpy as np

from printready.fixes._common import evolve, refuse
from printready.geometry import bbox, longest_edge_run
from printready.profile import Profile
from printready.types import Artwork, FixResult, Spec

EXTRA_PX = 2  # beyond the border, so the cut never touches the canvas edge


def pad_canvas(art: Artwork, spec: Spec, profile: Profile) -> FixResult:
    """Pad each side whose margin is under max_bridge_border_in (+2 px); updates offset.
    Refused when the art is cut off at the edge (run over edge_cut_min_run_in): padding cannot
    restore missing art and would hide the crop from the edge_crop check."""
    if art.subject is None:
        return refuse(art, "Padding needs the background removed first.")
    box = bbox(art.subject)
    if box is None:
        return refuse(art, "There is no art to pad around.")
    run = longest_edge_run(art.subject)
    if run.length_px / art.ppi > profile.edge_cut_min_run_in:
        return refuse(
            art,
            f"The art is cut off along the {run.edge} edge ({run.length_px / art.ppi:.2f} in); padding cannot restore it.",
            run_in=round(run.length_px / art.ppi, 4),
        )
    need = int(math.ceil(profile.max_bridge_border_in * art.ppi)) + EXTRA_PX
    x0, y0, x1, y1 = box
    left, top = max(0, need - x0), max(0, need - y0)
    right, bottom = max(0, need - (art.width - x1)), max(0, need - (art.height - y1))
    if not (left or top or right or bottom):
        return refuse(art, "The art already has room for the border; nothing to pad.")
    pads = ((top, bottom), (left, right))
    new = evolve(
        art,
        rgba=np.pad(art.rgba, (*pads, (0, 0))),
        subject=np.pad(art.subject, pads),
        cut=None if art.cut is None else np.pad(art.cut, pads),
        offset=(art.offset[0] + left, art.offset[1] + top),
    )
    measured = {"left_px": left, "top_px": top, "right_px": right, "bottom_px": bottom, "margin_in": round(need / art.ppi, 4)}
    note = f"Added transparent space around the art (up to {max(pads[0] + pads[1])} px) so the border fits."
    return FixResult(art=new, ok=True, note=note, measured=measured)
