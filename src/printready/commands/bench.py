"""`printready bench generate | run | report`: planted-defect benchmark (chunks K2, K2b)."""

from __future__ import annotations

import argparse
from pathlib import Path

from printready.commands import not_implemented

SPLITS = ("dev", "test")


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "bench",
        help="planted-defect benchmark",
        description="Generate the planted-defect benchmark, run a mode on it, and report.",
    )
    actions = p.add_subparsers(dest="bench_action", metavar="ACTION", required=True)

    gen = actions.add_parser("generate", help="write benchmark PNGs and the manifest")
    gen.add_argument("--split", choices=SPLITS, default="dev")
    gen.set_defaults(func=run_generate)

    runp = actions.add_parser("run", help="run a mode over a split")
    runp.add_argument("--split", choices=SPLITS, default="dev")
    runp.add_argument("--mode", choices=("rules", "agent"), default="rules")
    runp.add_argument("--model", default=None, help="agent/vision model, e.g. openrouter:x-ai/grok-4.7")
    runp.add_argument("--env-file", type=Path, default=None, help="dotenv file to load API keys from")
    runp.set_defaults(func=run_run)

    rep = actions.add_parser("report", help="write confusion matrices and a figure")
    rep.add_argument("--split", choices=SPLITS, default="dev")
    rep.set_defaults(func=run_report)


def run_generate(args: argparse.Namespace) -> int:
    return not_implemented("bench", "K2")


def run_run(args: argparse.Namespace) -> int:
    return not_implemented("bench", "K2b")


def run_report(args: argparse.Namespace) -> int:
    return not_implemented("bench", "K2b")
