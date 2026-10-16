"""`printready realset gen | label | eval`: real image set (chunk K5)."""

from __future__ import annotations

import argparse
from pathlib import Path

from printready.commands import not_implemented, positive_int

CHUNK = "K5"


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "realset",
        help="real generated images: generate, label, evaluate",
        description="Generate real images from prompts, label them by keypress, and evaluate agreement.",
    )
    actions = p.add_subparsers(dest="realset_action", metavar="ACTION", required=True)

    gen = actions.add_parser("gen", help="generate images from a prompt list")
    gen.add_argument("--prompts", type=Path, default=Path("realset/prompts.txt"), help="one prompt per line")
    gen.add_argument("--image-model", default="xai:grok-imagine-image", help="image model id")
    gen.add_argument("--n", type=positive_int, default=1, help="images per prompt")
    gen.add_argument("--env-file", type=Path, default=None, help="dotenv file to load API keys from")
    gen.set_defaults(func=run)

    label = actions.add_parser("label", help="local page, one keypress per image")
    label.add_argument("dir", metavar="DIR", type=Path, help="run directory with images")
    label.set_defaults(func=run)

    ev = actions.add_parser("eval", help="agreement tables: rules vs agent vs labels")
    ev.add_argument("dir", metavar="DIR", type=Path, help="run directory with reports and labels")
    ev.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    return not_implemented("realset", CHUNK)
