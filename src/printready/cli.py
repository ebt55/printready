"""Command line entry point. Each command group registers itself from printready.commands.<group>."""

from __future__ import annotations

import argparse

from printready import __version__
from printready.commands import bench, check, fix, realset

GROUPS = (check, fix, bench, realset)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="printready",
        description="Check and fix die-cut sticker artwork against a printer's paraphrased rules.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)
    for group in GROUPS:
        group.register(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
