"""`printready mcp`: serve check/fix/rules as MCP tools over stdio (needs the `mcp` extra)."""

from __future__ import annotations

import argparse
import sys


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "mcp",
        help="serve printready as MCP tools over stdio",
        description="Run an MCP server (stdio) with check_artwork, fix_artwork and get_rules. "
        "Install the extra first: uv sync --extra mcp",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    try:
        import mcp  # noqa: F401 - only checking the optional extra is installed
    except ImportError:
        print("mcp: the MCP SDK is not installed; run `uv sync --extra mcp` first", file=sys.stderr)
        return 2
    from printready.mcp_server import main

    main()
    return 0
