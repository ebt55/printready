"""`edge_crop` check: does the art run into the edge of the image?

Measures the longest run of subject pixels along any canvas edge. Longer than edge_cut_min_run_in
means the art is cut off (person). A shorter touch, or a built cut that runs off the canvas, is
fixed by pad_canvas (auto)."""

from __future__ import annotations

from printready.checks._common import not_applicable, rounded, skip_needs_mask
from printready.geometry import edge_pixel_count, longest_edge_run, min_margin_px
from printready.profile import Profile
from printready.types import Artwork, Finding, Spec


def check_edge_crop(art: Artwork, spec: Spec, profile: Profile) -> Finding:
    if art.shape == "rounded_rect":
        return not_applicable("edge_crop")
    if art.subject is None:
        return skip_needs_mask("edge_crop")
    run = longest_edge_run(art.subject)
    run_in = run.length_px / art.ppi
    margin = min_margin_px(art.subject)
    cut_on_edge = art.cut is not None and edge_pixel_count(art.cut) > 0
    measured = {
        "longest_run_in": rounded(run_in),
        "longest_run_px": run.length_px,
        "edge": run.edge or None,
        "edge_px": edge_pixel_count(art.subject),
        "min_margin_in": None if margin is None else rounded(margin / art.ppi),
        "limit_in": profile.edge_cut_min_run_in,
        "cut_on_edge": cut_on_edge,
    }
    boxes = [run.box(art.rgba.shape)] if run.length_px else []
    if run_in > profile.edge_cut_min_run_in:
        msg = (
            f"The art runs off the {run.edge} edge of the image for {run_in:.2f} in, so part of it is cut off; "
            "a person needs to check it."
        )
        return Finding("edge_crop", "fail", msg, measured, "person", boxes)
    if run.length_px > 0:
        msg = f"The art touches the {run.edge} edge of the image; we can add transparent space so the border fits."
        return Finding("edge_crop", "warn", msg, measured, "auto", boxes)
    if cut_on_edge:
        msg = "The border runs off the edge of the image; we can add transparent space so it fits."
        return Finding("edge_crop", "warn", msg, measured, "auto")
    return Finding("edge_crop", "pass", "The art does not touch the edges of the image.", measured, "none")
