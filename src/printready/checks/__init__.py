"""Deterministic checks: one module per check, each a pure function of (Artwork, Spec, Profile).

`run_checks` runs them in DETERMINISTIC_CHECK_IDS order and returns one Finding each (the text
checks need a vision model and live in printready.vision). A check never measures what a fix added
(border pixels, padding), so re-checking after a fix only moves the checks that fix addresses.
After fit_shape the art is a whole-image rounded rectangle: the cut-around-the-art checks report
"not applicable" and a seventh finding, product_fit, tells the customer about the product change."""

from __future__ import annotations

from printready.checks.alpha import check_soft_alpha
from printready.checks.background import check_background
from printready.checks.edges import check_edge_crop
from printready.checks.file import check_file, load_failure
from printready.checks.islands import check_islands
from printready.checks.product import check_product_fit
from printready.checks.resolution import check_resolution
from printready.profile import Profile
from printready.types import DETERMINISTIC_CHECK_IDS, Artwork, Finding, Report, Spec

CHECKS = (check_file, check_resolution, check_background, check_soft_alpha, check_edge_crop, check_islands)


def run_checks(art: Artwork, spec: Spec, profile: Profile) -> Report:
    """One Finding per deterministic check, in DETERMINISTIC_CHECK_IDS order. Checks that need a
    subject mask report `skip` ("needs background removal first") while `art.subject` is None.
    A rounded-rectangle order adds the product_fit finding. Pure: never modifies `art`. Boxes are
    in the coordinates of `art.rgba`."""
    findings = [check(art, spec, profile) for check in CHECKS]
    product = check_product_fit(art, spec, profile)
    return Report(findings + ([product] if product is not None else []))


def load_failure_report(reason: str) -> Report:
    """Report for a file that could not be opened (ImageLoadError): `file` fail, fixer none,
    every other check skipped."""
    skipped = [
        Finding(c, "skip", "Not checked because the file could not be opened.", {"reason": "file did not load"}, "none")
        for c in DETERMINISTIC_CHECK_IDS
        if c != "file"
    ]
    return Report([load_failure(reason), *skipped])


__all__ = ["CHECKS", "load_failure_report", "run_checks"]
