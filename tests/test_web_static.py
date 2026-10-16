"""Static checks on the workbench's CSS and JS (no browser needed)."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from printready.web.paths import STATIC_DIR

CSS = {p.name: p.read_text(encoding="utf-8") for p in (STATIC_DIR / "css").glob("*.css")}
DECORATIVE_KEYFRAMES = {"pulse-dot"}  # blinking status dots; never on content


def keyframes(text: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r"@keyframes\s+([\w-]+)\s*\{", text):
        depth, i = 1, m.end()
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out[m.group(1)] = text[m.end():i]
    return out


def test_content_never_waits_for_an_animation():
    """Content must be visible on the first frame even if no animation ever runs (background
    tabs, reduced motion): entry animations may move things, never fade them in."""
    for name, text in CSS.items():
        for frame, body in keyframes(text).items():
            if "opacity" in body:
                assert frame in DECORATIVE_KEYFRAMES, f"{name}: @keyframes {frame} animates opacity"
                assert not re.search(r"opacity:\s*0(\.0+)?\s*;", body), f"{name}: {frame} goes fully transparent"
        assert not re.search(r"animation-fill-mode:\s*(backwards|both)", text), name
        assert not re.search(r"animation:[^;]*\b(backwards|both)\b", text), name


def test_reduced_motion_is_honoured():
    assert any("prefers-reduced-motion: reduce" in text for text in CSS.values())


def test_no_pseudo_element_tooltips():
    """Tooltips are one fixed-position element (ui.js); pseudo-element tooltips widened scroll
    areas even while invisible."""
    for name, text in CSS.items():
        assert "attr(data-tip)" not in text, name


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_every_module_parses():
    for path in sorted((STATIC_DIR / "js").glob("*.js")):
        result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
        assert result.returncode == 0, f"{path.name}: {result.stderr}"
