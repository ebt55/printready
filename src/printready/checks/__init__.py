"""Deterministic checks (chunk K1). One module per check family lives in this package."""

from __future__ import annotations

from printready.profile import Profile
from printready.types import Artwork, Report, Spec


def run_checks(art: Artwork, spec: Spec, profile: Profile) -> Report:
    """Run every deterministic check and return one Finding per check id.

    Order follows DETERMINISTIC_CHECK_IDS: file, resolution, background, soft_alpha, edge_crop,
    islands, internal_cut. Checks that need a subject mask report `skip` ("needs background
    removal first") while `art.subject` is None. Pure: never modifies `art`.
    """
    raise NotImplementedError("K1")
