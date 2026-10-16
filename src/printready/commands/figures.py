"""`printready figures`: rebuild the README figures from saved results."""

from __future__ import annotations

import argparse
from pathlib import Path

SPLITS = ("dev", "test")


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "figures",
        help="rebuild the README figures from results",
        description="Write hero.png, gallery-strip.png, outcomes.png (real set) and bench-heat.png "
        "(benchmark metrics) from saved results. Image ids are sha256 prefixes (6+ characters) or "
        "<prompt id>/<image model>, e.g. d06/grok-imagine-image-2.0.",
    )
    p.add_argument("--realset-split", choices=SPLITS, default="dev")
    p.add_argument("--bench-split", choices=SPLITS, default="dev")
    p.add_argument("-o", "--out", type=Path, default=Path("docs/img"), help="output folder (default: docs/img)")
    p.add_argument("--hero", default=None, help="real-set image for hero.png (default: first fixable one)")
    p.add_argument("--gallery", nargs="+", default=None, metavar="ID", help="six real-set images for the gallery")
    p.add_argument("--mode", choices=("rules", "agent"), default="rules", help="whose outputs to show")
    p.add_argument("--root", type=Path, default=Path("."), help="repo root (default: .)")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from printready.figures import build_all

    print(f"figures: real set {args.realset_split} ({args.mode} mode), bench {args.bench_split}")
    written = build_all(args.root, args.out, realset_split=args.realset_split, bench_split=args.bench_split,
                        hero_id=args.hero, gallery_ids=args.gallery, mode=args.mode)
    for path in written:
        print(f"  wrote {path}")
    return 0
