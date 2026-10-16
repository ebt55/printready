"""`printready serve`: the local workbench (chunk K10).

    printready serve [--port 8765] [--open]            live: runs the real pipeline
    printready serve --demo [--demo-speed 1]           replays saved runs; nothing is charged
    printready serve --rebuild-demo                    rebuilds examples/samples/demo/ from the real pipeline
    printready serve --label DIR [--pass 1|2]          blind keypress labelling (what `realset label` starts)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from printready.commands import positive_float


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "serve",
        help="local workbench in the browser (127.0.0.1)",
        description="Start the local workbench: drop art, run rules or agent mode, inspect findings, "
                    "proofs and agent traces. Binds 127.0.0.1 only.",
    )
    p.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default 8765)")
    p.add_argument("--open", action="store_true", help="open the browser")
    p.add_argument("--demo", action="store_true", help="replay saved demo runs; no model calls, nothing charged")
    p.add_argument("--demo-speed", type=float, default=1.0, help="demo replay time factor (0 = instant)")
    p.add_argument("--rebuild-demo", action="store_true", help="rebuild examples/samples/demo/ and exit")
    p.add_argument("--redraw-samples", action="store_true", help="with --rebuild-demo: redraw the sample images too")
    p.add_argument("--real-only", action="store_true",
                   help="with --rebuild-demo: refresh only the real Grok examples (dev set) from results/realset/dev")
    p.add_argument("--out", type=Path, default=None, help="run store (default out/workbench/)")
    p.add_argument("--show-test", action="store_true",
                   help="show the real-set TEST split in Results (blind until Ebin's pass 2 is done)")
    p.add_argument("--label", type=Path, default=None, metavar="DIR", help="label mode over the images in DIR")
    p.add_argument("--pass", dest="pass_no", type=int, choices=(1, 2), default=1, help="label pass (default 1)")
    p.add_argument("--labels", type=Path, default=None, help="labels.jsonl path (default DIR/labels.jsonl)")
    p.add_argument("--items", type=Path, default=None,
                   help="label items manifest JSON [{image, proof, path}] instead of scanning DIR")
    p.add_argument("--caption-size", type=positive_float, default=3.0, help="size in the pass-1 caption (inches)")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from printready.web import demo
    from printready.web.server import AppConfig, run_server

    if args.rebuild_demo and args.real_only:
        index = demo.rebuild_real_examples()
        print(f"done: {sum(1 for v in index['runs'].values() if v.get('real'))} real example runs")
        return 0
    if args.rebuild_demo:
        print("rebuilding the demo folder ...")
        index = demo.build_demo(redraw_samples=args.redraw_samples)
        print(f"done: {len(index['runs'])} sample runs, real set {index['realset']}")
        return 0

    root = Path.cwd()
    if args.label is not None:
        from printready.web.label import LabelSession, items_from_dir, items_from_manifest

        manifest = args.label / f"label-pass{args.pass_no}.json"
        if not args.items and manifest.exists():  # written by `printready realset label`
            session = LabelSession.from_label_file(manifest)
            return run_server(AppConfig(root=root, label=session), port=args.port, open_browser=args.open)
        if args.items:
            items = items_from_manifest(args.items)
        elif args.pass_no == 1:
            items = items_from_dir(args.label)
        else:
            print(f"printready serve: {manifest} not found; `printready realset label --pass 2` writes it "
                  "(it de-duplicates the proofs by hash)", file=sys.stderr)
            return 1
        if not items:
            print(f"printready serve: no images to label in {args.label}", file=sys.stderr)
            return 1
        labels = args.labels or (args.label / "labels.jsonl")
        session = LabelSession(items, labels, args.pass_no, caption=f"{args.caption_size:g} in die-cut sticker")
        return run_server(AppConfig(root=root, label=session), port=args.port, open_browser=args.open)

    if args.demo and not demo.load_index():
        print("no demo folder yet; building it from the real pipeline (a few minutes) ...")
        demo.build_demo()
    return run_server(AppConfig(root=root, out_dir=args.out, demo=args.demo, demo_speed=max(0.0, args.demo_speed),
                                show_test=args.show_test),
                      port=args.port, open_browser=args.open)
