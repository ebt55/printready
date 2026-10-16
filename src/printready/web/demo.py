"""`printready serve --demo`: saved runs replayed with their recorded timing.

The demo folder (examples/samples/demo/) is DATA produced by the real pipeline, never hand-written
fixtures. It is rebuilt with one command, `printready serve --rebuild-demo`:

    demo/index.json                 what was built and when
    demo/runs/<sample>/<mode>/      one saved run per bundled sample and mode:
        events.jsonl                the on_event stream, each line with "_t" (ms since start)
        report.json, fixed.png, proof.png, cutline.svg, overlay.png, report.html,
        customer_message.md, step-*.png, look-*.png, log.jsonl (agent)
    demo/data/realset/demo/         a small demo "real set", laid out exactly like a real split
    demo/results/realset/demo/      ... its rules and agent runs, runs.jsonl and summary.json
    demo/results/bench/<split>/     illustrative benchmark numbers (marked "demo": true), shown
                                    only when the repo has no real benchmark results

Rules runs are pipeline.run_rules; agent runs are agent.run_agent. Only the model is scripted
(demo_script.py, via llm's fake provider), so every finding, fix, guard result, proof and outcome
is the real code's output. The UI labels all of it demo.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from printready.web import demo_script
from printready.web import samples as samplemod
from printready.web.paths import demo_dir as default_demo_dir
from printready.web.paths import samples_dir as default_samples_dir

DEMO_SIZE_IN = 3.0
DEMO_MODEL = "xai:grok-4.3"  # what the scripted runs stand in for (prices and labels)
MIN_GAP_S = 0.32  # replays space events at least this far apart, so the stream is visible


def load_samples(samples_dir: Path | None = None) -> list[dict]:
    path = (samples_dir or default_samples_dir()) / "samples.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def load_index(demo_dir: Path | None = None) -> dict:
    path = (demo_dir or default_demo_dir()) / "index.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def canned_run_dir(sample_id: str, mode: str, size_in: float, vision: bool, demo_dir: Path | None = None) -> Path | None:
    """The saved run matching this request exactly, or None (then the run happens live)."""
    demo_dir = demo_dir or default_demo_dir()
    entry = load_index(demo_dir).get("runs", {}).get(f"{sample_id}/{mode}")
    if not entry or abs(entry["size_in"] - size_in) > 1e-9 or bool(entry["vision"]) != bool(vision):
        return None
    d = demo_dir / entry["dir"]
    return d if (d / "events.jsonl").exists() else None


def read_events(run_dir: Path) -> list[dict]:
    path = run_dir / "events.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def replay(source: Path, dest: Path, emit: Callable[[dict], None], speed: float = 1.0) -> None:
    """Copy a saved run's files into `dest`, then re-emit its events with the recorded timing
    (at least MIN_GAP_S apart; `speed` scales every wait, 0 = instant)."""
    dest.mkdir(parents=True, exist_ok=True)
    for f in source.iterdir():
        if f.is_file() and f.name != "events.jsonl":
            shutil.copy2(f, dest / f.name)
    last_t = 0.0
    for ev in read_events(source):
        t = ev.pop("_t", 0) / 1000.0
        wait = max(t - last_t, MIN_GAP_S) * speed
        last_t = t
        if wait > 0:
            time.sleep(wait)
        emit(ev)


def spaced(emit: Callable[[dict], None], speed: float) -> Callable[[dict], None]:
    """Wrap a sink so live demo events arrive at least MIN_GAP_S apart (rules mode is very fast)."""
    state = {"last": 0.0}

    def _emit(event: dict) -> None:
        now = time.monotonic()
        wait = state["last"] + MIN_GAP_S * speed - now
        if wait > 0 and state["last"]:
            time.sleep(wait)
        state["last"] = time.monotonic()
        emit(event)

    return _emit


# ------------------------------------------------------------------ running one image for the demo

def run_demo_image(image: Path, out: Path, mode: str, emit: Callable[[dict], None], *, size_in: float = DEMO_SIZE_IN,
                   vision: dict | None = None, use_vision: bool = True, agent_opts: dict | None = None,
                   speed: float = 1.0) -> dict:
    """Run the real pipeline on one image with the scripted model. Returns the RunResult dict.

    rules: run_rules with a scripted vision answer (when `use_vision` and an answer is known).
    agent: a throwaway rules run plans the conversation, then run_agent plays it over the real tools.
    """
    from printready.web.runner import call_run_agent, call_run_rules

    agent_opts = agent_opts or {}
    with tempfile.TemporaryDirectory(prefix="printready-demo-") as tmp:
        ledger = Path(tmp) / "ledger.jsonl"  # scripted calls never touch results/spend-ledger.jsonl
        if mode == "rules":
            client = demo_script.make_client([demo_script.vision_response(vision)], ledger, speed) \
                if use_vision and vision is not None else None
            return call_run_rules(image, size_in, out, emit, client=client)
        plan = call_run_rules(image, size_in, Path(tmp) / "plan", lambda ev: None)
        responses = demo_script.agent_responses(
            plan, size_in, vision=vision if use_vision else None, look_note=agent_opts.get("look_note"),
            handoff=agent_opts.get("handoff"), handoff_note=agent_opts.get("handoff_note"))
        client = demo_script.make_client(responses, ledger, speed)
        return call_run_agent(image, size_in, out, emit, model=DEMO_MODEL, client=client)


def build_one(image: Path, out: Path, mode: str, *, size_in: float = DEMO_SIZE_IN, vision: dict | None = None,
              agent_opts: dict | None = None) -> dict:
    """Run one image into `out` (cleared first) and save its events with their timing."""
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    events: list[dict] = []
    start = time.monotonic()

    def record(ev: dict) -> None:
        events.append({**json.loads(json.dumps(ev, default=str)), "_t": int((time.monotonic() - start) * 1000)})

    result = run_demo_image(image, out, mode, record, size_in=size_in, vision=vision, agent_opts=agent_opts)
    with open(out / "events.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for ev in events:
            fh.write(json.dumps(ev) + "\n")
    slim(out)
    return result


SLIM_PREVIEW_PX = 640


def slim(run_dir: Path) -> None:
    """Keep the committed demo folder small. fixed.png, cutline.svg, report.json and events stay
    exactly as the pipeline wrote them; renders are compressed and two derived files are dropped:
    report.html (the same data with inline images) and overlay.png (the stage draws the boxes).
    Step previews are downscaled; the workbench stretches a preview over the run's canvas."""
    from PIL import Image

    for name in ("report.html", "overlay.png"):
        (run_dir / name).unlink(missing_ok=True)
    for path in sorted(run_dir.glob("step-*.png")):
        with Image.open(path) as im:
            im.load()
            if max(im.size) > SLIM_PREVIEW_PX:
                k = SLIM_PREVIEW_PX / max(im.size)
                im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
            im.save(path, optimize=True)
    for path in [run_dir / "proof.png", *sorted(run_dir.glob("look-*.png"))]:
        if not path.exists():
            continue
        with Image.open(path) as im:
            im.load()
            rgba = im.convert("RGBA")
        if rgba.getchannel("A").getextrema()[0] == 255:  # opaque renders compress well as 256 colours
            rgba.convert("RGB").quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)
        else:
            rgba.save(path, optimize=True)


def build_demo(samples_dir: Path | None = None, demo_dir: Path | None = None, redraw_samples: bool = False,
               realset: bool = True, log: Callable[[str], None] = print) -> dict:
    """Rebuild the whole demo folder from the real pipeline. Returns the new index."""
    samples_dir = samples_dir or default_samples_dir()
    demo_dir = demo_dir or default_demo_dir()
    if redraw_samples or not (samples_dir / "samples.json").exists():
        samplemod.write_samples(samples_dir)
    manifest = load_samples(samples_dir)
    if demo_dir.exists():
        shutil.rmtree(demo_dir)
    demo_dir.mkdir(parents=True)
    index = {"version": 2, "engine": "run_rules + run_agent (scripted model)",
             "built": datetime.now(timezone.utc).isoformat(timespec="seconds"), "size_in": DEMO_SIZE_IN,
             "model": DEMO_MODEL, "runs": {}, "realset": None, "bench": []}
    for s in manifest:
        for mode in ("rules", "agent"):
            rel = f"runs/{s['id']}/{mode}"
            result = build_one(samples_dir / s["file"], demo_dir / rel, mode, vision=s.get("vision"),
                               agent_opts=s.get("agent"))
            index["runs"][f"{s['id']}/{mode}"] = {"sample": s["id"], "mode": mode, "size_in": DEMO_SIZE_IN,
                                                   "vision": True, "model": DEMO_MODEL, "dir": rel,
                                                   "outcome": result["outcome"]}
            log(f"  {s['id']:8} {mode:5} -> {result['outcome']}")
    if realset:
        index["realset"] = build_demo_realset(demo_dir, log=log)
    index["bench"] = write_demo_bench(demo_dir / "results" / "bench")
    (demo_dir / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    return index


# ------------------------------------------------------------------ the demo "real set"

# Colour and size variants of the samples, laid out exactly like a real-set split (the demo folder
# is a miniature repo root): data/realset/demo/ and results/realset/demo/. Image models are named
# demo-gen-1/2 on purpose: these are procedural drawings, not model output. Labels are scripted so
# every filter has content; summary.json comes from printready.realset.evaluate itself.
REALSET_SPLIT = "demo"
REALSET_PLAN = [
    # kind, generator, demo pass-1 label (None = the fact matching the rules outcome), agent options
    ("mascot", 1, None, {}),
    ("mascot", 2, "fixable_diecut", {}),
    ("scene", 1, "scene", {}),
    ("scene", 2, "scene", {}),
    ("badge", 1, "needs_person", {}),
    ("badge", 2, "needs_person", {}),
    ("bolt", 1, "fixable_diecut", {}),
    ("bolt", 2, "needs_person", {"handoff": "too few pixels for a useful size",
                                  "handoff_note": "Under 100 PPI even at 2 in; ask the customer for a larger file."}),
    ("cloud", 1, "fixable_diecut", {}),
    ("cloud", 2, "fixable_diecut", {"handoff": "the bridge band would cross the drop",
                              "handoff_note": "Check that the white bridge between cloud and drop looks intended."}),
    ("ghost", 1, "needs_person", {}),
    ("ghost", 2, "fixable_diecut", {}),
    ("planet", 1, "ready_diecut", {}),
    ("planet", 2, "ready_diecut", {}),
    ("cat", 1, "needs_person", {}),
    ("cat", 2, "needs_person", {}),
]
PROMPTS = {
    "mascot": "a cheerful round mascot with a sprout on its head, sticker style",
    "badge": "a round coffee club badge that says COFFEE CLUB, est 2026",
    "bolt": "a lightning bolt logo inside a starburst",
    "cloud": "a smiling cloud dropping one raindrop, kawaii sticker",
    "ghost": "a cute glowing ghost sticker",
    "planet": "a ringed planet sticker with flat colours",
    "cat": "a grey cat sitting, full body, sticker",
    "scene": "a sunset over mountains and a lake, sticker",
}
UNACCEPTABLE = {("cloud", 2, "rules"), ("bolt", 1, "agent")}  # demo pass-2 "n" labels


def _draw_variant(kind: str, gen: int):
    s = samplemod.SAMPLE_BY_ID[kind]
    if gen == 1:  # the first "model": the other colour palette
        img = s.draw(palette=1)
    else:  # the second "model" outputs smaller images: fewer pixels per inch at 3 in
        base = s.draw()
        img = base.resize((int(base.width * 0.74), int(base.height * 0.74)), resample=3)
    if img.getchannel("A").getextrema()[0] == 255:
        img = img.convert("RGB")
    return img


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def _statuses(report: dict) -> dict:
    return {f["check"]: {"status": f["status"], "fixer": f["fixer"]} for f in report["findings"]}


def _run_row(result: dict, entry: dict, out: Path, root: Path) -> dict:
    """The same row realset.runs.summarize writes, from a RunResult dict."""
    history = result.get("history") or []
    fixed = out / "fixed.png"
    return {"image": entry["sha256"], "prompt_id": entry["prompt_id"], "image_model": entry["model"],
            "mode": result["mode"], "model": DEMO_MODEL if result["mode"] == "agent" else None,
            "outcome": result["outcome"], "handoff_reason": result.get("handoff_reason"),
            "shape": (result.get("art") or {}).get("shape", "die_cut"),
            "before": _statuses(result["before"]), "after": _statuses(result["after"]),
            "steps": [{"fix": h["fix"], "ok": h["ok"], "damaged": h["damaged"]} for h in history],
            "damaged": any(h["damaged"] for h in history), "cost_usd": round(result.get("cost_usd", 0.0), 6),
            "elapsed_s": round(result.get("elapsed_s", 0.0), 3),
            "fixed_sha256": _sha(fixed) if fixed.exists() else None,
            "out_dir": out.relative_to(root).as_posix(), "customer_message": result.get("customer_message")}


def build_demo_realset(root: Path, log: Callable[[str], None] = print) -> str:
    data = root / "data" / "realset" / REALSET_SPLIT
    res = root / "results" / "realset" / REALSET_SPLIT
    (data / "images").mkdir(parents=True, exist_ok=True)
    manifest, runs, label_rows = [], {"rules": [], "agent": []}, []
    ts = "2026-10-18T09:00:00.000Z"
    for i, (kind, gen, label, agent_override) in enumerate(REALSET_PLAN, start=1):
        tmp = data / "images" / f"_{kind}-{gen}.png"
        img = _draw_variant(kind, gen)
        img.save(tmp, optimize=True)
        sha = _sha(tmp)
        img_path = data / "images" / f"{sha}.png"
        tmp.replace(img_path)
        entry = {"prompt_id": f"x{i:02d}", "prompt": PROMPTS[kind], "model": f"demo-gen-{gen}",
                 "sha256": sha, "file": f"images/{sha}.png", "bytes": img_path.stat().st_size,
                 "width": img.width, "height": img.height, "format": "PNG"}
        manifest.append(entry)
        sample = samplemod.SAMPLE_BY_ID[kind]
        outcomes = {}
        for mode in ("rules", "agent"):
            out = res / mode / sha
            opts = {**sample.agent, **(agent_override if mode == "agent" else {})}
            result = build_one(img_path, out, mode, vision=sample.vision, agent_opts=opts)
            runs[mode].append(_run_row(result, entry, out, root))
            outcomes[mode] = result["outcome"]
        fact = label or {"ready": "ready_diecut", "fixable": "fixable_diecut"}.get(outcomes["rules"], outcomes["rules"])
        label_rows.append({"ts": ts, "pass": 1, "image": sha, "proof": None, "label": fact})
        log(f"  realset {kind}-{gen}: rules {outcomes['rules']}, agent {outcomes['agent']}, label {label_rows[-1]['label']}")
    # pass 2: every distinct proof either mode would send (outcome not needs_person), by fixed.png hash
    seen: dict[str, dict] = {}
    for mode in ("rules", "agent"):
        for (kind, gen, _, _), row in zip(REALSET_PLAN, runs[mode]):
            sha = row["fixed_sha256"]
            if row["outcome"] == "needs_person" or not sha or sha in seen:
                continue
            seen[sha] = row
            label_rows.append({"ts": ts, "pass": 2, "image": row["image"], "proof": sha,
                               "label": "unacceptable" if (kind, gen, mode) in UNACCEPTABLE else "acceptable"})
    _jsonl(data / "manifest.jsonl", manifest)
    _jsonl(data / "labels.jsonl", label_rows)
    for mode in ("rules", "agent"):
        _jsonl(res / mode / "runs.jsonl", runs[mode])
    # what the demo label page shows, in the realset label files' format
    pass1 = [{"image": e["sha256"], "proof": None, "file": e["file"]} for e in manifest]
    pass2 = [{"image": r["image"], "proof": sha, "file": f"../../../{r['out_dir']}/proof.png"} for sha, r in seen.items()]
    for n, items in ((1, pass1), (2, pass2)):
        (data / f"label-pass{n}.json").write_text(json.dumps(
            {"pass": n, "caption": "3 in die-cut sticker", "keys": {}, "labels": "labels.jsonl", "items": items},
            indent=2) + "\n", encoding="utf-8")
    try:  # the agreement summary, written by the real-set chunk's own evaluator
        from printready.realset import Paths
        from printready.realset.evaluate import evaluate

        evaluate(Paths(REALSET_SPLIT, root))
    except Exception as exc:
        log(f"  realset eval failed ({exc.__class__.__name__}: {exc}); writing the demo summary instead")
        _demo_summary(res, manifest, runs, label_rows)
    return f"results/realset/{REALSET_SPLIT}"


# PREREG mapping from Ebin's pass-1 facts to outcomes (03-EVAL.md).
LABEL_OUTCOME = {"ready_diecut": "ready", "fixable_diecut": "fixable", "scene": "fixable", "needs_person": "needs_person",
                 "ready": "ready", "fixable": "fixable"}


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "total": 0.0, "mean": 0.0, "median": 0.0, "max": 0.0}
    v = sorted(values)
    mid = v[len(v) // 2] if len(v) % 2 else (v[len(v) // 2 - 1] + v[len(v) // 2]) / 2
    return {"n": len(v), "total": round(sum(v), 4), "mean": round(sum(v) / len(v), 4), "median": round(mid, 4),
            "max": round(v[-1], 4)}


def _demo_summary(res: Path, manifest: list[dict], runs: dict, label_rows: list[dict]) -> None:
    """DEMO ONLY: summary.json in the shape `realset eval` writes, used when that evaluator cannot
    read the demo labels. Real numbers always come from `printready realset eval`."""
    outcomes = ("ready", "fixable", "needs_person")
    pass1 = {r["image"]: r["label"] for r in label_rows if r["pass"] == 1}
    pass2 = {r["proof"]: r["label"] for r in label_rows if r["pass"] == 2}
    by_mode = {m: {r["image"]: r for r in rows} for m, rows in runs.items()}
    labelled = [e["sha256"] for e in manifest if e["sha256"] in pass1]
    modes = {}
    for mode, rows in by_mode.items():
        scored = [s for s in labelled if s in rows]
        matrix = {o: {p: 0 for p in outcomes} for o in outcomes}
        for s in scored:
            matrix[LABEL_OUTCOME[pass1[s]]][rows[s]["outcome"]] += 1
        proofs = {r["fixed_sha256"] for r in rows.values() if r["outcome"] != "needs_person" and r.get("fixed_sha256")}
        unacceptable = sum(1 for p in proofs if pass2.get(p) == "unacceptable")
        damaged = sum(1 for r in rows.values() if r.get("damaged"))
        agree = sum(rows[s]["outcome"] == LABEL_OUTCOME[pass1[s]] for s in scored)
        modes[mode] = {"n_runs": len(rows), "n_scored": len(scored), "agree": agree,
                       "agree_rate": round(agree / len(scored), 3) if scored else None, "matrix": matrix,
                       "outcomes": {o: sum(r["outcome"] == o for r in rows.values()) for o in outcomes},
                       "proofs_to_label": len(proofs), "proofs_unlabelled": sum(1 for p in proofs if p not in pass2),
                       "unacceptable": unacceptable, "damaged": damaged, "bad_fixes": unacceptable + damaged,
                       "cost_usd": _stats([r["cost_usd"] for r in rows.values()]),
                       "elapsed_s": _stats([r["elapsed_s"] for r in rows.values()])}
    right = {m: {s for s in labelled if s in by_mode[m] and by_mode[m][s]["outcome"] == LABEL_OUTCOME[pass1[s]]}
             for m in by_mode}
    paired = {"n": len(labelled), "both_agree": len(right["rules"] & right["agent"]),
              "only_rules_agrees": len(right["rules"] - right["agent"]),
              "only_agent_agrees": len(right["agent"] - right["rules"]),
              "neither": len(set(labelled) - right["rules"] - right["agent"])}
    margin = modes["agent"]["agree"] - modes["rules"]["agree"]
    keep = margin >= 5 and modes["agent"]["bad_fixes"] <= modes["rules"]["bad_fixes"]
    cards = []
    for e in manifest:
        card = {"image": e["sha256"], "prompt_id": e["prompt_id"], "image_model": e["model"], "file": e["file"],
                "sampled": True, "label": pass1.get(e["sha256"])}
        for mode in ("rules", "agent"):
            r = by_mode[mode].get(e["sha256"])
            card[mode] = None if r is None else {"outcome": r["outcome"], "handoff_reason": r["handoff_reason"],
                                                 "out_dir": r["out_dir"], "proof_label": pass2.get(r.get("fixed_sha256")),
                                                 "damaged": r.get("damaged", False)}
        cards.append(card)
    summary = {
        "split": REALSET_SPLIT, "demo": True, "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_images": len(manifest), "sample": {"n": len(manifest), "labelled_pass1": len(labelled)},
        "labels": {"pass1": {k: sum(v == k for v in pass1.values()) for k in sorted(set(pass1.values()))},
                   "pass2": {k: sum(v == k for v in pass2.values()) for k in sorted(set(pass2.values()))}},
        "modes": modes, "paired": paired,
        "verdict": {"status": "keep_agent" if keep else "keep_rules",
                    "rule": "agent becomes the default only if it agrees with Ebin on at least 5 more of the labelled "
                            "images than rules mode and has no more bad fixes (unacceptable or damaged)",
                    "reason": f"agent agrees on {modes['agent']['agree']}, rules on {modes['rules']['agree']} "
                              f"(margin {margin:+d}, needs +5); bad fixes agent {modes['agent']['bad_fixes']}, "
                              f"rules {modes['rules']['bad_fixes']}",
                    "agent_minus_rules": margin},
        "rules_by_image_model": {}, "images": cards,
    }
    (res / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")


def write_demo_bench(out: Path) -> list[str]:
    """Illustrative benchmark numbers in the metrics.json shape, clearly marked "demo": true."""
    def cm(rows, cols, counts):
        return {"rows": rows, "cols": cols, "counts": counts}

    pwf, cols = ["pass", "warn", "fail"], ["pass", "warn", "fail", "skip"]
    splits = []
    for split, j in (("dev", 0), ("test", 1)):
        checks = {
            "file": {"n": 258, "matrix": cm(["pass", "fail"], cols, [[258, 0, 0, 0], [0, 0, 0, 0]]),
                     "recall": None, "clean_false_flag": 0.0, "fixer_agreement": None},
            "resolution": {"n": 82, "matrix": cm(pwf, cols, [[54 - j, j, 0, 0], [1, 13, 0, 0], [0, 0, 14, 0]]),
                           "recall": 0.964, "clean_false_flag": 0.0, "fixer_agreement": 1.0},
            "background": {"n": 80, "matrix": cm(["pass", "fail"], cols, [[40, 0, 0, 0], [1 + j, 0, 39 - j, 0]]),
                           "recall": round(0.975 - 0.025 * j, 3), "clean_false_flag": 0.0, "fixer_agreement": 0.949},
            "soft_alpha": {"n": 64, "matrix": cm(pwf, cols, [[46, 2, 0, 0], [1, 15, 0, 0], [0, 0, 0, 0]]),
                           "recall": 0.9375, "clean_false_flag": 0.025, "fixer_agreement": 1.0},
            "edge_crop": {"n": 64, "matrix": cm(pwf, cols, [[40, 0, 0, 0], [0, 8, 0, 0], [0, 1, 15, 0]]),
                          "recall": 0.958, "clean_false_flag": 0.0, "fixer_agreement": 0.958},
            "islands": {"n": 80, "matrix": cm(pwf, cols, [[56, 0, 0, 0], [0, 0, 0, 0], [0, 0, 24 - j, j]]),
                        "recall": round(1.0 - 0.042 * j, 3), "clean_false_flag": 0.0, "fixer_agreement": 0.917},
        }
        metrics = {
            "split": split, "demo": True, "n": 258, "generated": "2026-10-18", "checks": checks,
            "fix_success": {"n": 104, "ok": 100 - j, "rate": round((100 - j) / 104, 3)},
            "outcome": {"n": 258, "accuracy": round(0.934 - 0.012 * j, 3),
                        "matrix": cm(["ready", "fixable", "needs_person"], ["ready", "fixable", "needs_person"],
                                     [[38, 2, 0], [3, 98 - j, 4 + j], [0, 8, 105]])},
            "vision": {"text_garbled": {"precision": 0.875, "recall": round(0.875 - 0.06 * j, 3), "n": 48},
                       "text_small": {"precision": 0.667, "recall": 0.5, "n": 48}},
        }
        d = out / split
        d.mkdir(parents=True, exist_ok=True)
        (d / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        splits.append(split)
    return splits
