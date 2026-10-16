"""`printready site build`: a static, read-only copy of the workbench for GitHub Pages (chunk K10).

    printready site build --realset results/realset/<run> --bench test -o site/
    printready site build --demo -o site/        # from the bundled demo folder (reproducible)

The folder opens from file:// and from any static host: no server, no API, no external URLs.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "site",
        help="static read-only export of the workbench",
        description="Build a static, read-only copy of Results and saved Workbench views.",
    )
    actions = p.add_subparsers(dest="site_action", metavar="ACTION", required=True)
    b = actions.add_parser("build", help="write the static site into a folder")
    b.add_argument("--realset", type=Path, default=None, help="real-set run folder, e.g. results/realset/<run>")
    b.add_argument("--bench", action="append", choices=("dev", "test"), default=None,
                   help="benchmark split(s) to include (repeatable; default: every split with results)")
    b.add_argument("--demo", action="store_true", help="build from the bundled demo folder")
    b.add_argument("-o", "--out", type=Path, required=True, help="output folder (replaced)")
    b.set_defaults(func=run_build)


def run_build(args: argparse.Namespace) -> int:
    from printready.web.export import ExportError, build_site

    try:
        summary = build_site(args.out, realset=args.realset, bench=args.bench, demo=args.demo, root=Path.cwd())
    except ExportError as exc:
        print(f"printready site build: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {summary['files']} files ({summary['bytes'] / 1e6:.1f} MB) to {args.out}: "
          f"{summary['items']} real-set items, {summary['samples']} sample runs, bench {summary['bench'] or 'none'}")
    print(f"open {Path(args.out) / 'index.html'}")
    return 0
