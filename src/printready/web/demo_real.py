"""Real Grok examples for the demo: saved runs from the DEV real set, replayed in the workbench.

DEV split only. Blinding: nothing is ever read from data/realset/test or results/realset/test.
The model turns are real grok-4.3 output (log.jsonl); the event stream is rebuilt from the saved
run (report.json, step previews, log.jsonl) with the recorded latencies, so a replay streams like
the live run did. The UI labels these "real Grok output, dev set".
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Callable

REAL_SPLIT = "dev"  # never "test"
FIX_TOOLS = ("remove_background", "pad_canvas", "add_border", "bridge_islands", "fit_shape")
SEVERITY = {"pass": 0, "warn": 1, "fail": 2}

# sha256 prefix in the dev manifest, id, title, one line on what it shows
REAL_EXAMPLES = [
    ("5604338c", "real-maple-moss", "Maple & Moss mascot", "Die-cut: the background comes off, the agent reads the text."),
    ("225dd236", "real-salt-pine", "Salt & Pine badge", "Die-cut badge; the agent checks, borders and reads the lettering."),
    ("16de6b3e", "real-moon-cat", "Cat on a starry moon", "A scene: a rounded-rectangle sticker via fit_shape."),
    ("e40a6619", "real-kindness", "Choose Kindness", "Slogan sticker with hand lettering; die-cut."),
    ("7cf81092", "real-maple-cafe", "Maple & Moss café", "A photo-like scene: rounded rectangle, no cutout."),
]
DROP = ("report.html",)  # same data with inline images; the workbench is the viewer


def _jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _report_from(findings: list[dict]) -> dict:
    ranked = [f.get("status") for f in findings if f.get("status") in SEVERITY]
    status = max(ranked, key=SEVERITY.__getitem__) if ranked else "skip"
    return {"status": status, "findings": [{"boxes": [], "measured": {}, **f} for f in findings]}


def rebuild_events(run_dir: Path, report: dict, mode: str) -> list[dict]:
    """The on_event stream of a saved run, each event with "_t" (ms since start)."""
    events: list[dict] = []
    clock = {"t": 0}

    def add(event: dict, dt: int) -> None:
        clock["t"] += max(0, int(dt))
        events.append({**event, "_t": clock["t"]})

    history = report.get("history") or (report.get("art") or {}).get("history") or []
    outputs = report.get("outputs") or {}
    add({"type": "findings", "stage": "before", "report": report["before"]}, 350)
    if mode == "rules":
        for i, step in enumerate(history, start=1):
            add({"type": "step", "index": i, "step": step, "preview": outputs.get(f"step-{i}")}, 450)
    else:
        step_i = 0
        for turn in (r for r in _jsonl(run_dir / "log.jsonl") if r.get("type") == "turn"):
            clock["t"] += int(turn.get("latency_ms") or 800)  # the model answers ...
            for call in turn.get("tool_calls") or []:  # ... then its tools run, in order
                ms = int(call.get("ms") or 0)
                content = call.get("content") if isinstance(call.get("content"), dict) else {}
                if call.get("name") in FIX_TOOLS and step_i < len(history):
                    step_i += 1
                    add({"type": "step", "index": step_i, "step": history[step_i - 1],
                         "preview": outputs.get(f"step-{step_i}")}, ms)
                elif call.get("name") in ("check", "read_text") and content.get("findings"):
                    stage = "check" if call["name"] == "check" else "read_text"
                    add({"type": "findings", "stage": stage, "report": _report_from(content["findings"])}, ms)
                else:
                    clock["t"] += ms
            add({k: v for k, v in turn.items()}, 40)
    add({"type": "findings", "stage": "after", "report": report["after"]}, 220)
    add({"type": "done", "result": report}, 160)
    return events


def build_real_examples(demo_dir: Path, root: Path, log: Callable[[str], None] = print) -> tuple[list[dict], dict]:
    """Copy the chosen DEV runs into demo_dir/real/ and return (sample entries, index run entries)."""
    from printready.web.demo import slim

    data = root / "data" / "realset" / REAL_SPLIT
    res = root / "results" / "realset" / REAL_SPLIT
    manifest = {e["sha256"]: e for e in _jsonl(data / "manifest.jsonl") if e.get("sha256")}
    runs = {m: {r.get("image"): r for r in _jsonl(res / m / "runs.jsonl")} for m in ("rules", "agent")}
    base = demo_dir / "real"
    if base.exists():
        shutil.rmtree(base)
    samples, index = [], {}
    for prefix, ex_id, title, blurb in REAL_EXAMPLES:
        sha = next((s for s in manifest if s.startswith(prefix)), None)
        if sha is None:
            log(f"  real example {ex_id}: not in the dev manifest, skipped")
            continue
        entry = manifest[sha]
        src = data / entry["file"]
        if not src.is_file():
            log(f"  real example {ex_id}: image missing, skipped")
            continue
        dest = base / ex_id
        dest.mkdir(parents=True)
        original = dest / f"original{src.suffix.lower()}"
        shutil.copy2(src, original)
        for mode in ("rules", "agent"):
            row = runs[mode].get(sha)
            run_src = (root / row["out_dir"]) if row and row.get("out_dir") else None
            if run_src is None or not (run_src / "report.json").is_file():
                continue
            out = dest / mode
            out.mkdir()
            for f in run_src.iterdir():
                if f.is_file() and f.name not in DROP:
                    shutil.copy2(f, out / f.name)
            report = json.loads((out / "report.json").read_text(encoding="utf-8"))
            events = rebuild_events(out, report, mode)
            with open(out / "events.jsonl", "w", encoding="utf-8", newline="\n") as fh:
                for ev in events:
                    fh.write(json.dumps(ev) + "\n")
            slim(out)
            index[f"{ex_id}/{mode}"] = {"sample": ex_id, "mode": mode, "size_in": 3.0, "vision": True,
                                        "model": row.get("model") or "xai:grok-4.3", "dir": f"real/{ex_id}/{mode}",
                                        "outcome": report.get("outcome"), "real": True}
            log(f"  real {ex_id:16} {mode:5} -> {report.get('outcome')} ({(report.get('art') or {}).get('shape')})")
        from PIL import Image

        with Image.open(original) as im:
            w, h = im.size
        samples.append({"id": ex_id, "title": title, "blurb": blurb, "file": f"real/{ex_id}/{original.name}",
                        "base": "demo", "size_in": 3.0, "width": w, "height": h, "group": "real",
                        "note": "real Grok output, dev set", "prompt": entry.get("prompt"),
                        "image_model": entry.get("model"), "vision": None, "agent": {}})
    (base).mkdir(parents=True, exist_ok=True)
    (base / "real.json").write_text(json.dumps(samples, indent=2) + "\n", encoding="utf-8")
    return samples, index
