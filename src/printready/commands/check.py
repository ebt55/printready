"""`printready check ART --size 3`: deterministic report to stdout and out/<name>/ (chunk K1)."""

from __future__ import annotations

import argparse
from pathlib import Path

from printready.commands import not_implemented, positive_float

CHUNK = "K1"


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "check",
        help="check artwork against the profile (no changes)",
        description="Run the deterministic checks on one image at the ordered size.",
    )
    p.add_argument("art", metavar="ART", type=Path, help="artwork file (PNG, JPG or WebP)")
    p.add_argument(
        "--size", type=positive_float, required=True,
        help="longest side of the finished sticker in inches, border included",
    )
    p.add_argument("--profile", type=Path, default=None, help="profile YAML (default: shipped die-cut profile)")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    return not_implemented("check", CHUNK)
