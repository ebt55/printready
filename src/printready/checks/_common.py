"""Helpers shared by the check modules."""

from __future__ import annotations

from printready.types import Finding

NEEDS_MASK = "needs background removal first"


def skip_needs_mask(check: str) -> Finding:
    """The finding for a mask-based check while the image is opaque and unremoved."""
    return Finding(
        check=check,
        status="skip",
        message="Not checked yet: the background has to be removed first.",
        measured={"reason": NEEDS_MASK},
        fixer="none",
    )


def r(value: float, places: int = 4) -> float:
    """Round a measurement for report.json."""
    return round(float(value), places)
