"""Rules-only mode (chunk K3).

Fixed order: check -> remove_background if background fail/auto -> pad_canvas if edge_crop warn
-> add_border -> bridge_islands if islands fail/auto -> re-check -> vision text check if a model is
configured -> decide. Both modes write the same outputs per image in out/<name>/: report.json,
fixed.png, cutline.svg, proof.png, overlay.png, report.html, customer_message.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from printready.profile import Profile
from printready.types import Artwork, Spec


def run_rules(art: Artwork, spec: Spec, profile: Profile, model: str | None = None) -> dict[str, Any]:
    """Run rules mode on one artwork and return the result (before/after reports, fixed art,
    outcome, customer message, person notes) for write_outputs."""
    raise NotImplementedError("K3")


def write_outputs(result: dict[str, Any], out_dir: Path) -> None:
    """Write the per-image output files for a rules or agent result into `out_dir`."""
    raise NotImplementedError("K3")
