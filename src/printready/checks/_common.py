"""Helpers shared by the check modules: the skip finding for mask-based checks on art that still
has its background, and rounding for the numbers that go into report.json."""

from __future__ import annotations

from printready.types import Finding

NEEDS_MASK = "needs background removal first"
NOT_APPLICABLE = "Not applicable to a whole-image sticker."


def skip_needs_mask(check: str) -> Finding:
    """The finding for a mask-based check while the image is opaque and unremoved."""
    return Finding(
        check=check,
        status="skip",
        message="Not checked yet: the background has to be removed first.",
        measured={"reason": NEEDS_MASK},
        fixer="none",
    )


def not_applicable(check: str) -> Finding:
    """A cut-around-the-art check on a whole-image sticker: a pass that says it does not apply
    (not a skip, which would mean "could not verify" and send the image to a person)."""
    return Finding(check=check, status="pass", message=NOT_APPLICABLE, measured={"applies": False}, fixer="none")


def rounded(value: float, places: int = 4) -> float:
    """Round a measurement for report.json."""
    return round(float(value), places)
