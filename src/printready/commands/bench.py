"""`printready bench generate | run | report`: planted-defect benchmark (chunks K2, K2b)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from printready.commands import positive_float, positive_int

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
        "sample of a split; write results/bench/<split>/predictions.jsonl (offline). With --vision, instead "
        "run the live vision text check on the text family and write vision.jsonl (prints the cost "
        "estimate first; spends nothing without --yes).",
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
    runp.add_argument("--vision", action="store_true", help="live vision check on the text family only")
    runp.add_argument("--model", default="xai:grok-4.3", help="vision model (default: xai:grok-4.3)")
    runp.add_argument("--yes", action="store_true", help="make the paid calls (otherwise print the estimate)")
    runp.add_argument("--resume", action="store_true",
                      help="with --vision: keep samples already answered by the same model, call only the rest")
    runp.add_argument("--max-usd", type=positive_float, default=0.15,
                      help="refuse if the estimate is above this, and stop if spend reaches it (default 0.15)")
    runp.add_argument("--env-file", type=Path, default=None, help="dotenv file with the API key (default: .env)")
    runp.set_defaults(func=run_run)

    rep = actions.add_parser(
        "report",
        help="write confusion matrices and a figure",
        description="Score predictions.jsonl (and vision.jsonl, if present) against the manifest: "
        "report.md, metrics.json, confusion.png.",
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
    from printready.bench.run import BenchDataError, run_split, run_vision

    try:
        if args.vision:
            info = run_vision(args.split, args.root, model=args.model, yes=args.yes, resume=args.resume,
                              max_usd=args.max_usd,
                              limit=args.limit, manifest=args.manifest, profile_path=args.profile,
                              env_file=args.env_file)
            return 0 if info["ran"] or not args.yes else 1
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
