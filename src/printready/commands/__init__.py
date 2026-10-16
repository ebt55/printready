"""CLI command groups. Each module defines `register(subparsers)` for its own group, so later
chunks only touch their own module. Handlers take the parsed args and return an exit code."""

from __future__ import annotations

import argparse
import sys

NOT_IMPLEMENTED_EXIT = 2


def not_implemented(group: str, chunk: str) -> int:
    """Placeholder handler body until the owning chunk fills it in."""
    print(f"{group}: not implemented yet (chunk {chunk})", file=sys.stderr)
    return NOT_IMPLEMENTED_EXIT


def positive_float(text: str) -> float:
    """argparse type: a number greater than zero."""
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not value > 0:
        raise argparse.ArgumentTypeError(f"must be greater than zero: {text!r}")
    return value


def positive_int(text: str) -> int:
    """argparse type: an integer greater than zero."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1: {text!r}")
    return value
