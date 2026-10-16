"""`printready bench generate | run | report`: planted-defect benchmark (chunks K2, K2b)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from printready.commands import positive_int

SPLITS = ("dev", "test")


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "bench",
        help="planted-defect benchmark",
        description="Generate the planted-defect benchmark, run a mode on it, and report.",
    )
    actions = p.add_subparsers(dest="bench_action", metavar="ACTION", required=True)

    gen = actions.add_parser(
        "generate",
        help="write benchmark PNGs and the manifest",
        description="Render the planted-defect benchmark into data/bench/<split>/ and write "
        "data/bench/manifest-<split>.jsonl. The test split needs a committed PREREG.md.",
    )
    gen.add_argument("--split", choices=SPLITS, default="dev")
    gen.add_argument("--limit", type=positive_int, default=None,
                     help="only the first N samples of each family (writes manifest-<split>-limitN.jsonl)")
    gen.add_argument("--jobs", type=positive_int, default=None, help="worker processes (default: up to 8)")
    gen.add_argument("--root", type=Path, default=Path("."),
                     help="repo root that data/bench/ and results/bench/ live under (default: .)")
    gen.add_argument("--profile", type=Path, default=None,
                     help="profile YAML (default: shipped die-cut profile)")
    gen.set_defaults(func=run_generate)

    runp = actions.add_parser(
        "run",
        help="run the detectors and the rules pipeline over a split",
        description="Run the deterministic checks (BEFORE) and the whole rules pipeline (AFTER) on every "
        "sample of a split; write results/bench/<split>/predictions.jsonl. Offline: no vision, no agent.",
    )
    runp.add_argument("--split", choices=SPLITS, default="dev")
    runp.add_argument("--limit", type=positive_int, default=None,
                      help="only the first N samples of each family (writes results/bench/<split>/limitN/)")
    runp.add_argument("--jobs", type=positive_int, default=None, help="worker processes (default: up to 8)")
    runp.add_argument("--root", type=Path, default=Path("."), help="repo root (default: .)")
    runp.add_argument("--manifest", type=Path, default=None,
                      help="manifest to run (default: data/bench/manifest-<split>.jsonl)")
    runp.add_argument("--profile", type=Path, default=None,
                      help="profile YAML (default: shipped die-cut profile)")
    runp.set_defaults(func=run_run)

    rep = actions.add_parser(
        "report",
        help="write confusion matrices and a figure",
        description="Score predictions.jsonl against the manifest: report.md, summary.json, confusion.png.",
    )
    rep.add_argument("--split", choices=SPLITS, default="dev")
    rep.add_argument("--limit", type=positive_int, default=None, help="score a --limit N run")
    rep.add_argument("--root", type=Path, default=Path("."), help="repo root (default: .)")
    rep.add_argument("--manifest", type=Path, default=None,
                     help="manifest the run used (default: data/bench/manifest-<split>.jsonl)")
    rep.add_argument("--profile", type=Path, default=None,
                     help="profile YAML (default: shipped die-cut profile)")
    rep.set_defaults(func=run_report)


def run_generate(args: argparse.Namespace) -> int:
    from printready.bench.generate import PreregMissing, generate_split

    try:
        generate_split(args.split, args.root, limit=args.limit, jobs=args.jobs, profile_path=args.profile)
    except PreregMissing as exc:
        print(f"bench generate: {exc}", file=sys.stderr)
        return 1
    return 0


def run_run(args: argparse.Namespace) -> int:
    from printready.bench.run import BenchDataError, run_split

    try:
        run_split(args.split, args.root, limit=args.limit, jobs=args.jobs, manifest=args.manifest,
                  profile_path=args.profile)
    except BenchDataError as exc:
        print(f"bench run: {exc}", file=sys.stderr)
        return 1
    return 0


def run_report(args: argparse.Namespace) -> int:
    from printready.bench.report import report_split

    try:
        report_split(args.split, args.root, limit=args.limit, manifest=args.manifest, profile_path=args.profile)
    except FileNotFoundError as exc:
        print(f"bench report: {exc}", file=sys.stderr)
        return 1
    return 0
