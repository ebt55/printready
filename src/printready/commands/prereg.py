"""`printready prereg freeze | verify`: the frozen-artifacts block in PREREG.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "prereg",
        help="freeze and verify the preregistered artifacts",
        description="Hash the artifacts PREREG.md freezes (profile, dev manifest, bench generator, test "
        "prompts, model prompts, package source) and the model settings, and check them later.",
    )
    actions = p.add_subparsers(dest="prereg_action", metavar="ACTION", required=True)
    freeze = actions.add_parser("freeze", help="write or update the frozen block in PREREG.md")
    freeze.add_argument("--root", type=Path, default=None, help="repo root (default: this checkout)")
    freeze.set_defaults(func=run_freeze)
    verify = actions.add_parser("verify", help="recompute and compare with PREREG.md; exit 1 on any change")
    verify.add_argument("--root", type=Path, default=None, help="repo root (default: this checkout)")
    verify.set_defaults(func=run_verify)


def run_freeze(args: argparse.Namespace) -> int:
    from printready.prereg import SOURCE_GROUP, PreregError, freeze

    try:
        path, snap = freeze(args.root)
    except PreregError as exc:
        print(f"prereg freeze: {exc}", file=sys.stderr)
        return 1
    print(f"prereg freeze: wrote the frozen block to {path}")
    for label, entry in snap["files"].items():
        print(f"  {entry['sha256'][:12]}  {entry['path']}")
    src = snap["source"][SOURCE_GROUP]
    print(f"  {src['sha256'][:12]}  {SOURCE_GROUP}: {src['count']} files")
    for key, value in snap["settings"].items():
        print(f"  {key} = {value}")
    print("Commit PREREG.md before generating the test split.")
    return 0


def run_verify(args: argparse.Namespace) -> int:
    from printready.prereg import verify

    problems = verify(args.root)
    if problems:
        print("prereg verify: MISMATCH", file=sys.stderr)
        for line in problems:
            print(f"  {line}", file=sys.stderr)
        return 1
    print("prereg verify: OK (every frozen artifact and setting matches)")
    return 0
