"""`printready check ART --size 3`: deterministic report to stdout and out/<name>/ (report.json,
overlay.png). Exit 0 if nothing fails, 1 if any check fails, 2 on a usage or profile error."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from printready.checks import load_failure_report, run_checks
from printready.commands import positive_float
from printready.imageio import ImageLoadError, load_artwork
from printready.profile import ProfileError, load_profile
from printready.render import render_overlay
from printready.types import Report, Spec


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "check",
        help="check artwork against the profile (no changes)",
        description="Run the deterministic checks on one image at the ordered size.",
    )
    p.add_argument("art", metavar="ART", type=Path, help="artwork file (PNG, JPG or WebP)")
    p.add_argument(
        "--size", type=positive_float, required=True,
        help="longest side of the finished sticker in inches, border included",
    )
    p.add_argument("--profile", type=Path, default=None, help="profile YAML (default: shipped die-cut profile)")
    p.add_argument("--out", type=Path, default=Path("out"), help="output root; files go to OUT/<name>/ (default: out)")
    p.set_defaults(func=run)


def format_table(report: Report) -> str:
    rows = [("check", "status", "fixer", "message")]
    for f in report.findings:
        rows.append((f.check, f.status, f.fixer if f.status in ("warn", "fail") else "-", f.message))
    widths = [max(len(row[i]) for row in rows) for i in range(3)]
    lines = []
    for i, row in enumerate(rows):
        lines.append("  ".join(cell.ljust(widths[j]) for j, cell in enumerate(row[:3])) + "  " + row[3])
        if i == 0:
            lines.append("  ".join("-" * wd for wd in widths) + "  " + "-" * 7)
    return "\n".join(lines)


def summary(report: Report) -> str:
    counts = {s: sum(f.status == s for f in report.findings) for s in ("fail", "warn", "skip", "pass")}
    parts = ", ".join(f"{n} {s}" for s, n in counts.items() if n)
    return f"overall: {report.status()} ({parts})"


def run(args: argparse.Namespace) -> int:
    try:
        profile = load_profile(args.profile)
        spec = Spec("die_cut", args.size)
    except (ProfileError, ValueError) as exc:
        print(f"check: {exc}", file=sys.stderr)
        return 2
    try:
        art = load_artwork(args.art, spec, profile)
    except ImageLoadError as exc:
        art, report = None, load_failure_report(str(exc))
    except ValueError as exc:  # e.g. a size too small to hold the border
        print(f"check: {exc}", file=sys.stderr)
        return 2
    else:
        report = run_checks(art, spec, profile)

    out_dir = args.out / args.art.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [out_dir / "report.json"]
    data = {
        "spec": spec.to_dict(),
        "profile": profile.name,
        "art": art.to_dict() if art is not None else None,
        "report": report.to_dict(),
    }
    written[0].write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if art is not None:
        written.append(out_dir / "overlay.png")
        render_overlay(art, report).save(written[-1])

    print(f"{args.art.name} at {spec.size_in:g} in die-cut ({profile.name})")
    print(format_table(report))
    print(summary(report))
    print("wrote " + ", ".join(str(p) for p in written))
    return 1 if report.status() == "fail" else 0
