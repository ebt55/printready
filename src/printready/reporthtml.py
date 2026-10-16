"""Static report.html per image (chunk K3): before | after side by side, findings table,
customer message and person notes. No web framework; images referenced by relative path."""

from __future__ import annotations

from typing import Any


def report_html(result: dict[str, Any]) -> str:
    """Return a self-contained HTML page for one image's result."""
    raise NotImplementedError("K3")
