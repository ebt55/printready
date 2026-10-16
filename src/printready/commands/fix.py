"""`printready fix ART --size 3 [--mode rules|agent]`: check, fix, cut line, proof (chunk K3)."""

from __future__ import annotations

import argparse
from pathlib import Path

from printready.commands import not_implemented, positive_float

CHUNK = "K3"


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "fix",
        help="fix artwork and write proof, cut line and report",
        description="Check and fix one image, then write the per-image outputs to out/<name>/.",
    )
    p.add_argument("art", metavar="ART", type=Path, help="artwork file (PNG, JPG or WebP)")
    p.add_argument(
        "--size", type=positive_float, required=True,
        help="longest side of the finished sticker in inches, border included",
    )
    p.add_argument("--profile", type=Path, default=None, help="profile YAML (default: shipped die-cut profile)")
    p.add_argument("--mode", choices=("rules", "agent"), default="rules", help="fixed rules or tool-use agent")
    p.add_argument("--model", default=None, help="vision/agent model, e.g. openrouter:x-ai/grok-4.7")
    p.add_argument("--prompt", default=None, help="the prompt the art was generated from, if known")
    p.add_argument("--env-file", type=Path, default=None, help="dotenv file to load API keys from")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    return not_implemented("fix", CHUNK)
