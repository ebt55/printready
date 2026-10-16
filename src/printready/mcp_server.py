"""printready as MCP tools for agent clients (stdio): check, fix (rules mode only) and the rules.

The tool functions are plain Python and return JSON-ready dicts; the `mcp` SDK is an optional
extra (`uv sync --extra mcp`) imported only by `build_server`. No paid model calls happen here.
Tools never print: stdout belongs to the MCP stdio transport.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from printready import __version__
from printready.checks import load_failure_report, run_checks
from printready.imageio import ImageLoadError, load_artwork
from printready.pipeline import run_rules
from printready.profile import load_profile
from printready.types import Spec

INSTRUCTIONS = (
    "printready checks and fixes die-cut sticker artwork against Sticker Mule's published artwork rules "
    "(paraphrased; not affiliated). Sizes are the finished sticker's longest side in inches, border "
    "included. Outcomes: ready, fixable (mechanical fixes applied or a customer choice such as a smaller "
    "size), needs_person."
)


def _art_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"no such file: {p}")
    return p


def check_artwork(path: str, size_in: float) -> dict[str, Any]:
    """Check a sticker image (PNG, JPG or WebP) at the ordered size without changing it.
    Returns the overall status and one finding per check (file, resolution, background,
    soft_alpha, edge_crop, islands) with a plain message, the measured numbers and who can fix it."""
    profile = load_profile()
    spec = Spec("die_cut", float(size_in))
    art_path = _art_path(path)
    try:
        art = load_artwork(art_path, spec, profile)
        report, ppi = run_checks(art, spec, profile), round(art.ppi, 1)
    except ImageLoadError as exc:
        report, ppi = load_failure_report(str(exc)), None
    return {"file": str(art_path), "size_in": spec.size_in, "ppi": ppi, **report.to_dict()}


def fix_artwork(path: str, size_in: float, out_dir: str | None = None) -> dict[str, Any]:
    """Fix a sticker image in rules mode: remove a solid background, pad, add the white border,
    join nearby pieces, draw the die-cut line. Every fix passes a damage guard. Returns the outcome,
    findings before and after, each step with its guard numbers, the customer message and the
    output files (fixed.png, cutline.svg, proof.png, overlay.png, report.json, report.html).
    Outputs go to out_dir, default <image folder>/<image name>-printready/."""
    art_path = _art_path(path)
    target = Path(out_dir).expanduser().resolve() if out_dir else art_path.parent / f"{art_path.stem}-printready"
    run = run_rules(art_path, Spec("die_cut", float(size_in)), load_profile(), target)
    return {
        "outcome": run.outcome,
        "customer_message": run.customer_message,
        "person_notes": run.person_notes,
        "before": run.before.to_dict(),
        "after": run.after.to_dict(),
        "steps": [s.to_dict() for s in run.art.history] if run.art is not None else [],
        "outputs": {name: str(target / file) for name, file in run.outputs.items()},
        "elapsed_s": round(run.elapsed_s, 2),
    }


def get_rules() -> dict[str, Any]:
    """The die-cut rules in use: each rule's value, its source (a Sticker Mule FAQ URL, or
    "convention" where the FAQ gives no number) and a one-line reason."""
    profile = load_profile()
    return {
        "profile": profile.name,
        "product": profile.product,
        "note": "Paraphrased from Sticker Mule's public FAQ pages; not affiliated with Sticker Mule.",
        "rules": {
            key: {"value": getattr(profile, key), "source": profile.sources[key], "why": profile.whys[key]}
            for key in profile.sources
        },
    }


TOOLS = (check_artwork, fix_artwork, get_rules)


def build_server() -> Any:
    """An MCP server with the three tools (requires the `mcp` extra)."""
    try:
        from mcp.server.mcpserver import MCPServer  # mcp 2.x

        server = MCPServer("printready", instructions=INSTRUCTIONS, version=__version__)
    except ImportError:
        from mcp.server.fastmcp import FastMCP  # mcp 1.x

        server = FastMCP("printready", instructions=INSTRUCTIONS)
    for tool in TOOLS:
        server.add_tool(tool)
    return server


def main() -> None:
    build_server().run("stdio")
