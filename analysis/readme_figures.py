"""README figures from the TEST split (post hoc: built after pass 1 and pass 2 were labelled).

Lives outside src/ so the frozen, hashed package stays exactly as preregistered; it reuses the
drawing helpers of the frozen `printready.figures` and adds what the test figures need:
- the runs with the PREREG addendum 1 reruns in place (results/realset/<split>-rerun/),
- Ebin's pass-2 verdict per proof (labels.jsonl pass 2 + label-pass2-mapping.json),
- rounded-rectangle products (the cut line is an SVG <rect>),
- results.png: agreement with the ceiling, pass-2 acceptance, cost per image;
- prefix-strip.png: the same prompt as typed vs with a sticker-style prefix (exploratory run in
  data/realset/prefix and results/realset/prefix).

    uv run python analysis/readme_figures.py --realset-split test --bench-split test -o docs/img/ \\
        --hero bfeeafce --gallery 41e5d915 0dbb18b1 be61375e 49cac149 7fd718ba 0fe8bcb3 \
        --prefix p03 p05 p09 p19 p29 p36

Reads committed results and labels only (no API calls).
"""

from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from printready import figures as F
from printready.realset import Paths, last_by, read_jsonl
from printready.realset.rerun import rerun_runs

SHAPE_WORDS = {"die_cut": "die-cut", "rounded_rect": "rounded rectangle"}
STEP_WORDS = {**F.FIX_WORDS, "fit_shape": "whole-image rounded rectangle"}
VERDICT = {  # Ebin's pass 2 on the proof: would he send it to the customer?
    "acceptable": ("sent", "pass"),
    "unacceptable": ("not sent", "fail"),
    None: ("no proof: to a person", "skip"),
}


# --- data ------------------------------------------------------------------------------------------


def final_runs(root: Path, split: str, mode: str) -> dict[str, F.RealImage]:
    """Last run per image with the rerun (PREREG addendum 1) in place where there is one."""
    paths = Paths.for_split(split, root)
    manifest = {m["sha256"]: m for m in read_jsonl(paths.manifest)}
    runs = last_by(read_jsonl(paths.runs(mode)), "image")
    reruns = last_by(read_jsonl(rerun_runs(paths, mode)), "image")
    out = {}
    for sha, row in sorted(runs.items(), key=lambda kv: (kv[1]["prompt_id"], kv[1]["image_model"])):
        row = dict(reruns.get(sha, row), source="rerun" if sha in reruns else "original")
        m = manifest[sha]
        out[sha] = F.RealImage(sha, row["prompt_id"], m["prompt"], row["image_model"], paths.data / m["file"], row,
                               root / row["out_dir"])
    return out


def pass2_verdicts(root: Path, split: str) -> dict[tuple[str, str, str], str]:
    """(mode, image, source) -> Ebin's pass-2 label of the proof that run produced."""
    paths = Paths.for_split(split, root)
    by_proof = {r["proof"]: r["label"] for r in read_jsonl(paths.labels) if r["pass"] == 2}
    mapping = json.loads((paths.data / "label-pass2-mapping.json").read_text(encoding="utf-8"))
    return {(u["mode"], u["image"], u["source"]): by_proof.get(proof) for proof, uses in mapping.items() for u in uses}


def verdict_for(im: F.RealImage, verdicts, mode: str = "rules") -> str | None:
    return verdicts.get((mode, im.sha, im.run["source"]))


def steps_text(im: F.RealImage) -> str:
    done = [STEP_WORDS.get(s["fix"], s["fix"]) for s in im.report().get("history", []) if s["ok"]]
    return ", ".join(done) if done else "no changes"


# --- cut lines: <path> (die-cut, via the frozen reader) or <rect rx> (rounded rectangle) -----------


def rect_cut(out_dir: Path) -> list[list[tuple[float, float]]] | None:
    svg, fixed = out_dir / "cutline.svg", out_dir / "fixed.png"
    if not svg.exists() or not fixed.exists():
        return None
    text = svg.read_text(encoding="utf-8")
    vb = re.search(r'viewBox="\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*"', text)
    rect = re.search(r"<rect\b([^>]*)/?>", text)
    if not vb or not rect:
        return None
    attr = dict(re.findall(r'([\w-]+)="([-\d.]+)"', rect.group(1)))  # "stroke-width" is not "width"
    vx, vy, vw, _ = (float(v) for v in vb.groups())
    with Image.open(fixed) as im:
        k = im.width / vw
    x, y, w, h = (float(attr[a]) for a in ("x", "y", "width", "height"))
    r = float(attr.get("rx", attr.get("ry", 0)))
    pts = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for step in range(0, 91, 10):
            a = math.radians(a0 + step)
            pts.append(((cx + r * math.cos(a) - vx) * k, (cy + r * math.sin(a) - vy) * k))
    return [pts + [pts[0]]]


def cut_lines(out_dir: Path):
    return F.cut_paths(out_dir) or rect_cut(out_dir)


# --- hero ------------------------------------------------------------------------------------------


def hero(im: F.RealImage, size_in: float = 3.0) -> Image.Image:
    """The frozen hero layout, with the removed background shown as a pale wash under a red hatch
    (reads the same on any background colour) and the shape-aware step words."""
    report = im.report()
    panel = (F.WIDTH - 2 * F.MARGIN - 2 * F.GUTTER) // 3
    top = F.MARGIN + 44
    canvas = Image.new("RGB", (F.WIDTH, top + panel + 64 + F.MARGIN - 8), F.PAPER)
    draw = ImageDraw.Draw(canvas)
    original = Image.open(im.original).convert("RGB")
    xs = [F.MARGIN + k * (panel + F.GUTTER) for k in range(3)]
    titles = [f"Generated by {im.model_short}", "What the checks found", "Proof for the customer"]
    for k, (x, title) in enumerate(zip(xs, titles)):
        draw.text((x, F.MARGIN + 6), str(k + 1), font=F.font(20, True), fill=F.CUT, anchor="lt")
        draw.text((x + 24, F.MARGIN + 6), title, font=F.font(20, True), fill=F.INK, anchor="lt")
    F.card(canvas, (xs[0], top, xs[0] + panel, top + panel), original)

    arr = np.asarray(original, dtype=np.float64).copy()
    bg = F.background_mask(im, report, (original.height, original.width))
    if bg is not None:
        yy, xx = np.mgrid[0:original.height, 0:original.width]
        hatch = ((xx + yy) // 9) % 3 == 0
        arr[bg] = arr[bg] * 0.25 + np.array([244, 242, 237]) * 0.75  # wash toward paper
        red = np.array([224, 64, 47], dtype=np.float64)
        arr[bg & hatch] = arr[bg & hatch] * 0.35 + red * 0.65
    x, y, k = F.card(canvas, (xs[1], top, xs[1] + panel, top + panel), Image.fromarray(arr.astype(np.uint8)))
    findings = report["before"]["findings"]
    cy = y + 12
    for f in sorted(findings, key=lambda f: {"fail": 0, "warn": 1}.get(f["status"], 2)):
        label = F.short_label(f, size_in)
        if label:
            bg_c, ink_c, dot_c = F.STATUS.get(f["status"], F.STATUS["skip"])
            F.chip(draw, x + 12, cy, label, bg_c, ink_c, dot=dot_c)
            cy += 36
    if bg is not None:
        F.chip(draw, x + 12, cy, "hatched: removed as background", F.SURFACE, F.INK_2, size=13, bold=False)

    px, py, pk = F.card(canvas, (xs[2], top, xs[2] + panel, top + panel), F.proof_image(im))
    paths = cut_lines(im.out_dir)
    if paths:
        F.draw_cut(canvas, paths, px, py, pk)

    outcome = report["outcome"]
    cy = top + panel + 20
    bg_c, ink_c, _ = F.OUTCOME[outcome]
    w = F.chip(draw, F.MARGIN, cy, F.OUTCOME_LABEL[outcome], bg_c, ink_c, size=16)
    shape = SHAPE_WORDS.get(im.run.get("shape") or "die_cut", "die-cut")
    text = (f"\u201c{im.prompt}\u201d  ·  {size_in:g} in {shape}  ·  {report.get('mode', 'rules')} mode: "
            f"{steps_text(im)}")
    f = F.font(17)
    draw.text((F.MARGIN + w + 14, cy + 14), F.ellipsize(text, f, F.WIDTH - 2 * F.MARGIN - w - 14), font=f,
              fill=F.INK_2, anchor="lm")
    return canvas


# --- gallery ---------------------------------------------------------------------------------------


def gallery(images: list[F.RealImage], verdicts) -> Image.Image:
    cols, rows = 3, 2
    cell_w = (F.WIDTH - 2 * F.MARGIN - (cols - 1) * F.GUTTER) // cols
    thumb = (cell_w - 36) // 2
    cell_h = thumb + 98
    height = 2 * F.MARGIN + rows * cell_h + (rows - 1) * F.GUTTER
    canvas = Image.new("RGB", (F.WIDTH, height), F.PAPER)
    draw = ImageDraw.Draw(canvas)
    for n, im in enumerate(images[: cols * rows]):
        cx = F.MARGIN + (n % cols) * (cell_w + F.GUTTER)
        cy = F.MARGIN + (n // cols) * (cell_h + F.GUTTER)
        report = im.report()
        F.card(canvas, (cx, cy, cx + thumb, cy + thumb), Image.open(im.original).convert("RGB"))
        draw.text((cx + thumb + 18, cy + thumb / 2), "→", font=F.font(22, True), fill=F.INK_4, anchor="mm")
        ax = cx + thumb + 36
        if report["outcome"] == "needs_person":
            bg_c, ink_c, _ = F.OUTCOME["needs_person"]
            draw.rounded_rectangle([ax, cy, ax + thumb, cy + thumb], radius=12, fill=bg_c, outline=F.LINE, width=1)
            reasons = [F.short_label(f, 3.0) for f in report["after"]["findings"] if f["status"] in ("warn", "fail")]
            reasons = [r for r in reasons if r and "PPI" not in r] or [report.get("handoff_reason") or "a judgment call"]
            lines = F.wrap(reasons[0], F.font(14), thumb - 32)
            ty = cy + thumb / 2 - 10 * len(lines) - 4
            draw.text((ax + thumb / 2, ty), "sent to a person", font=F.font(16, True), fill=ink_c, anchor="mm")
            for i, line in enumerate(lines):
                draw.text((ax + thumb / 2, ty + 26 + 19 * i), line, font=F.font(14), fill=ink_c, anchor="mm")
        else:
            px, py, pk = F.card(canvas, (ax, cy, ax + thumb, cy + thumb), F.proof_image(im))
            paths = cut_lines(im.out_dir)
            if paths:
                F.draw_cut(canvas, paths, px, py, pk, width=1.8)
        # row 1: outcome + product; row 2: Ebin's pass-2 verdict; row 3: prompt; row 4: steps
        y = cy + thumb + 10
        bg_c, ink_c, _ = F.OUTCOME[report["outcome"]]
        w = F.chip(draw, cx, y, F.OUTCOME_LABEL[report["outcome"]], bg_c, ink_c, size=13)
        shape = im.run.get("shape") or "die_cut"
        if report["outcome"] != "needs_person":
            w += 8 + F.chip(draw, cx + w + 8, y, SHAPE_WORDS.get(shape, shape), F.SURFACE, F.INK_2, size=13,
                            bold=False)
        text, grade = VERDICT[verdict_for(im, verdicts)]
        bg_c, ink_c, dot = F.STATUS[grade]
        F.chip(draw, cx + w + 8, y, f"Ebin: {text}", bg_c, ink_c, size=13, dot=dot)
        f = F.font(14)
        draw.text((cx, y + 44), F.ellipsize(f"{im.prompt_id}  {im.prompt}", f, cell_w), font=f, fill=F.INK_2,
                  anchor="lm")
        detail = F.ellipsize(f"{im.model_short}  ·  {steps_text(im)}", F.font(12), cell_w)
        draw.text((cx, y + 68), detail, font=F.font(12), fill=F.INK_3, anchor="lm")
    return canvas


# --- outcomes by image model ------------------------------------------------------------------------

SEGMENTS = [  # (key, label, fill, label ink)
    ("ready", "ready", F.OUTCOME["ready"][2], "#ffffff"),
    ("fixable/die_cut", "fixable: die-cut", F.OUTCOME["fixable"][2], "#ffffff"),
    ("fixable/rounded_rect", "fixable: rounded rectangle", "#f3b5d6", F.OUTCOME["fixable"][1]),
    ("needs_person", "needs a person", F.OUTCOME["needs_person"][2], F.INK),
]


def outcome_rows(root: Path, split: str) -> list[tuple[str, dict[str, int]]]:
    rows = []
    for mode in ("rules", "agent"):
        by_model: dict[str, dict[str, int]] = {}
        for im in final_runs(root, split, mode).values():
            counts = by_model.setdefault(im.image_model, {k: 0 for k, *_ in SEGMENTS})
            o = im.run["outcome"]
            key = f"fixable/{im.run.get('shape') or 'die_cut'}" if o == "fixable" else o
            counts[key] += 1
        for model in sorted(by_model):
            rows.append((f"{model.split(':')[-1]}  ·  {mode}", by_model[model]))
    return rows


def outcomes(root: Path, split: str) -> Image.Image:
    data = outcome_rows(root, split)
    label_w, bar_h, gap = 360, 46, 22
    x0, x1 = F.MARGIN + label_w, F.WIDTH - F.MARGIN - 90
    height = F.MARGIN + 116 + len(data) * (bar_h + gap) + 40 + F.MARGIN
    canvas = Image.new("RGB", (F.WIDTH, height), F.PAPER)
    draw = ImageDraw.Draw(canvas)
    draw.text((F.MARGIN, F.MARGIN), f"Real images, {split} split: outcome per image model", font=F.font(26, True),
              fill=F.INK)
    draw.text((F.MARGIN, F.MARGIN + 38), "Rules mode on all 100 images; agent mode on the 50 Ebin labelled. "
              "Runs that never reached a model were re-attempted (PREREG addendum 1).", font=F.font(16), fill=F.INK_3)
    lx = F.MARGIN
    for _, label, fill, _ in SEGMENTS:
        draw.rounded_rectangle([lx, F.MARGIN + 76, lx + 18, F.MARGIN + 94], radius=4, fill=fill)
        draw.text((lx + 26, F.MARGIN + 85), label, font=F.font(15), fill=F.INK_2, anchor="lm")
        lx += 26 + F.text_width(label, F.font(15)) + 28
    y = F.MARGIN + 124
    for label, counts in data:
        total = sum(counts.values())
        draw.text((F.MARGIN, y + bar_h / 2), label, font=F.font(17, True), fill=F.INK, anchor="lm")
        x = x0
        for key, _, fill, ink in SEGMENTS:
            n = counts.get(key, 0)
            if not n:
                continue
            w = (x1 - x0) * n / total
            draw.rounded_rectangle([x + 1, y, x + w - 1, y + bar_h], radius=4, fill=fill)
            if w > 34:
                draw.text((x + w / 2, y + bar_h / 2), str(n), font=F.font(17, True), fill=ink, anchor="mm")
            x += w
        draw.text((x1 + 14, y + bar_h / 2), f"n = {total}", font=F.font(15), fill=F.INK_3, anchor="lm")
        y += bar_h + gap
    draw.text((F.MARGIN, y + 8), "No run can be ready: every generated image is an opaque JPEG, so each needs "
              "its background removed or a whole-image shape.", font=F.font(14), fill=F.INK_3, anchor="lm")
    return canvas


# --- results summary -------------------------------------------------------------------------------


def results_numbers(root: Path, split: str) -> dict[str, Any]:
    s = json.loads((root / "results" / "realset" / split / "summary.json").read_text(encoding="utf-8"))
    modes = (s.get("rerun") or {}).get("modes") or s["modes"]
    n = modes["rules"]["n_scored"]
    # outcome() never returns ready on these opaque images, so labels that map to ready cap agreement
    ready_labels = [k for k, v in s["mapping"]["prereg"].items() if v == "ready"]
    cannot = sum(s["labels"]["pass1"].get(k, 0) for k in ready_labels)
    p2 = s["labels"]["pass2"]
    return {
        "n": n, "ceiling": n - cannot, "cannot": cannot,
        "agree": {m: modes[m]["agree"] for m in ("rules", "agent")},
        "cost": {m: modes[m]["cost_usd"]["mean"] for m in ("rules", "agent")},
        "runs": {m: modes[m]["n_runs"] for m in ("rules", "agent")},
        "pass2": (p2.get("acceptable", 0), sum(p2.values())),
        "rerun": bool(s.get("rerun")),
    }


def _axis(draw, x0, x1, y, ticks, fmt):
    draw.line([x0, y, x1, y], fill=F.LINE_STRONG, width=1)
    lo, hi = ticks[0], ticks[-1]
    for t in ticks:
        x = x0 + (x1 - x0) * (t - lo) / (hi - lo)
        draw.line([x, y, x, y + 5], fill=F.LINE_STRONG, width=1)
        draw.text((x, y + 9), fmt(t), font=F.font(13), fill=F.INK_3, anchor="mt")


def results(root: Path, split: str) -> Image.Image:
    r = results_numbers(root, split)
    col_w = (F.WIDTH - 2 * F.MARGIN - 2 * 56) // 3
    xs = [F.MARGIN + k * (col_w + 56) for k in range(3)]
    top, bar_h = F.MARGIN + 118, 44
    height = top + 3 * bar_h + 160
    canvas = Image.new("RGB", (F.WIDTH, height), F.PAPER)
    draw = ImageDraw.Draw(canvas)
    draw.text((F.MARGIN, F.MARGIN), f"Real images, {split} split: results", font=F.font(26, True), fill=F.INK)
    draw.text((F.MARGIN, F.MARGIN + 38), f"{r['n']} images labelled by Ebin; rules mode ran on {r['runs']['rules']} "
              f"images, agent mode on {r['runs']['agent']}" + (", with the addendum 1 reruns" if r["rerun"] else ""),
              font=F.font(16), fill=F.INK_3)
    titles = ["Agrees with Ebin's label", "Proofs Ebin would send", "Model cost per image"]
    for x, t in zip(xs, titles):
        draw.text((x, top - 34), t, font=F.font(18, True), fill=F.INK)
    label_w = 74

    # 1: agreement on the 0..n axis, with the ceiling
    x, bx0 = xs[0], xs[0] + label_w
    bx1 = x + col_w - 10
    scale = lambda v: bx0 + (bx1 - bx0) * v / r["n"]  # noqa: E731
    for i, mode in enumerate(("rules", "agent")):
        y = top + i * (bar_h + 18)
        draw.text((x, y + bar_h / 2), mode, font=F.font(16, True), fill=F.INK, anchor="lm")
        draw.rectangle([bx0, y, bx1, y + bar_h], fill=F.SURFACE, outline=F.LINE)
        draw.rounded_rectangle([bx0, y, scale(r["agree"][mode]), y + bar_h], radius=4, fill=F.OUTCOME["ready"][2])
        draw.text((scale(r["agree"][mode]) - 10, y + bar_h / 2), f"{r['agree'][mode]}/{r['n']}", font=F.font(16, True),
                  fill="#ffffff", anchor="rm")
    cy0, cy1 = top - 8, top + 2 * bar_h + 18 + 8
    cxl = scale(r["ceiling"])
    for yy in range(int(cy0), int(cy1), 8):
        draw.line([cxl, yy, cxl, min(yy + 4, cy1)], fill=F.INK, width=2)
    draw.text((cxl + 6, cy0 - 2), f"ceiling {r['ceiling']}", font=F.font(13, True), fill=F.INK, anchor="lb")
    _axis(draw, bx0, bx1, cy1 + 6, [0, 10, 20, 30, 40, r["n"]], str)
    note = (f"Preregistered mapping (a scene counts as fixable). {r['cannot']} images Ebin called ready as is "
            f"cannot come out ready (every image is an opaque JPEG), so no mode can agree on more than "
            f"{r['ceiling']}.")
    for i, line in enumerate(F.wrap(note, F.font(13), col_w, max_lines=3)):
        draw.text((x, cy1 + 40 + 18 * i), line, font=F.font(13), fill=F.INK_3)

    # 2: pass-2 acceptance on 0..total
    ok, total = r["pass2"]
    x, bx0 = xs[1], xs[1] + label_w
    bx1 = x + col_w - 10
    y = top
    draw.text((x, y + bar_h / 2), "proofs", font=F.font(16, True), fill=F.INK, anchor="lm")
    draw.rectangle([bx0, y, bx1, y + bar_h], fill=F.SURFACE, outline=F.LINE)
    xe = bx0 + (bx1 - bx0) * ok / total
    draw.rounded_rectangle([bx0, y, xe, y + bar_h], radius=4, fill=F.OUTCOME["ready"][2])
    draw.text((xe - 10, y + bar_h / 2), f"{ok}/{total}", font=F.font(16, True), fill="#ffffff", anchor="rm")
    _axis(draw, bx0, bx1, y + bar_h + 8, [0, 10, 20, 30, 40, 50, total], str)
    note = (f"Pass 2: every distinct proof either mode produced, shown blind (image only). {ok} of {total} "
            f"were acceptable to send to a customer.")
    for i, line in enumerate(F.wrap(note, F.font(13), col_w, max_lines=3)):
        draw.text((x, y + bar_h + 44 + 18 * i), line, font=F.font(13), fill=F.INK_3)

    # 3: cost per image from $0
    x, bx0 = xs[2], xs[2] + label_w
    bx1 = x + col_w - 10
    hi = max(r["cost"].values())
    step = 0.002 if hi <= 0.012 else 0.005
    top_tick = step * math.ceil(hi / step)
    ticks = [round(step * k, 4) for k in range(int(round(top_tick / step)) + 1)]
    for i, mode in enumerate(("rules", "agent")):
        y = top + i * (bar_h + 18)
        v = r["cost"][mode]
        draw.text((x, y + bar_h / 2), mode, font=F.font(16, True), fill=F.INK, anchor="lm")
        xe = bx0 + (bx1 - bx0) * v / top_tick
        draw.rounded_rectangle([bx0, y, max(xe, bx0 + 6), y + bar_h], radius=4, fill="#5598e7")
        draw.text((xe + 8, y + bar_h / 2), f"${v:.4f}", font=F.font(16, True), fill=F.INK, anchor="lm")
    _axis(draw, bx0, bx1, top + 2 * bar_h + 18 + 14, ticks, lambda t: f"${t:.3f}")
    note = "Mean xAI spend per image from the spend ledger (vision for rules mode; every turn for the agent)."
    for i, line in enumerate(F.wrap(note, F.font(13), col_w, max_lines=3)):
        draw.text((x, top + 2 * bar_h + 18 + 48 + 18 * i), line, font=F.font(13), fill=F.INK_3)
    return canvas


# --- prefix strip ----------------------------------------------------------------------------------

PREFIX_MODEL = "xai:grok-imagine-image"


def prefix_runs(root: Path) -> tuple[dict[str, F.RealImage], str]:
    """Prefixed runs by prompt id (results/realset/prefix), and the prefix text itself."""
    data = root / "data" / "realset" / "prefix"
    manifest = {m["sha256"]: m for m in read_jsonl(data / "manifest.jsonl")}
    out, prefix = {}, ""
    for sha, row in last_by(read_jsonl(root / "results" / "realset" / "prefix" / "runs.jsonl"), "image").items():
        m = manifest[sha]
        if row["image_model"] != PREFIX_MODEL:
            continue
        out[row["prompt_id"]] = F.RealImage(sha, row["prompt_id"], m["prompt"], row["image_model"], data / m["file"],
                                            row, root / row["out_dir"])
        if m.get("full_prompt", "").endswith(m["prompt"]):
            prefix = m["full_prompt"][: -len(m["prompt"])].strip()
    return out, prefix


def prefix_pairs(root: Path, split: str = "test") -> list[tuple[F.RealImage, F.RealImage]]:
    """(as typed, with prefix) for every prompt where the typed prompt gave a scene that rules mode
    made a rounded rectangle, and the prefixed prompt gave a die-cut that rules mode could fix."""
    typed = {im.prompt_id: im for im in final_runs(root, split, "rules").values() if im.image_model == PREFIX_MODEL}
    prefixed, _ = prefix_runs(root)
    pairs = []
    for pid, a in sorted(typed.items()):
        b = prefixed.get(pid)
        if (b and a.run.get("shape") == "rounded_rect" and a.run["outcome"] == "fixable"
                and b.run.get("shape") == "die_cut" and b.run["outcome"] == "fixable"):
            pairs.append((a, b))
    return pairs


def _resolution(im: F.RealImage) -> tuple[float | None, str]:
    """The final resolution finding of a run: (PPI of the subject at the order size, status)."""
    for f in im.report()["after"]["findings"]:
        if f["check"] == "resolution":
            return (f.get("measured") or {}).get("ppi"), f["status"]
    return None, "skip"


def prefix_strip(root: Path, ids: list[str], split: str = "test", size_in: float = 3.0) -> Image.Image:
    pairs = {a.prompt_id: (a, b) for a, b in prefix_pairs(root, split)}
    missing = [i for i in ids if i not in pairs]
    if missing:
        raise SystemExit(f"prefix strip: {missing} do not qualify (scene as typed, die-cut with the prefix)")
    _, prefix = prefix_runs(root)
    n, gap = len(ids), 20
    cell = (F.WIDTH - 2 * F.MARGIN - (n - 1) * gap) // n
    head = F.MARGIN + 96
    row_title, chip_h = 34, 40
    row2 = head + row_title + cell + chip_h + 18
    caption_y = row2 + row_title + cell + chip_h + 6
    height = caption_y + 62 + 64 + F.MARGIN - 16
    canvas = Image.new("RGB", (F.WIDTH, height), F.PAPER)
    draw = ImageDraw.Draw(canvas)
    draw.text((F.MARGIN, F.MARGIN), "Same prompt, same model (grok-imagine-image): as typed vs with a sticker-style "
              "prefix", font=F.font(26, True), fill=F.INK)
    sub_text = f"Prefix: \u201c{prefix}\u201d" if prefix else "With a fixed sticker-style prefix."
    draw.text((F.MARGIN, F.MARGIN + 40), F.ellipsize(sub_text, F.font(16), F.WIDTH - 2 * F.MARGIN), font=F.font(16),
              fill=F.INK_3)
    for y, label in ((head, "As typed"), (row2, "With the sticker prefix")):
        draw.text((F.MARGIN, y), label, font=F.font(18, True), fill=F.INK)
    for k, pid in enumerate(ids):
        a, b = pairs[pid]
        x = F.MARGIN + k * (cell + gap)
        # as typed: the generated image, and what rules mode made of it
        F.card(canvas, (x, head + row_title, x + cell, head + row_title + cell), Image.open(a.original).convert("RGB"))
        F.chip(draw, x, head + row_title + cell + 8, "scene \u2192 rounded rectangle", F.SURFACE, F.INK_2, size=13,
               bold=False)
        # with the prefix: the die-cut proof and its cut line
        top = row2 + row_title
        px, py, pk = F.card(canvas, (x, top, x + cell, top + cell), F.proof_image(b))
        paths = F.cut_paths(b.out_dir)
        if paths:
            F.draw_cut(canvas, paths, px, py, pk, width=1.8)
        ppi, status = _resolution(b)
        label = f"die-cut, {ppi:.0f} PPI at {size_in:g} in" if ppi else "die-cut"
        s_bg, s_ink, s_dot = F.STATUS.get(status, F.STATUS["skip"])
        F.chip(draw, x, top + cell + 8, label, s_bg, s_ink, size=13, dot=s_dot)
        # the prompt, under its column
        for i, line in enumerate(F.wrap(f"{pid}  {a.prompt}", F.font(13), cell, max_lines=3)):
            draw.text((x, caption_y + 18 * i), line, font=F.font(13), fill=F.INK_2)
    foot = caption_y + 72
    draw.text((F.MARGIN, foot), "Exploratory, post hoc: one model, one fixed prefix, not preregistered.",
              font=F.font(14), fill=F.INK_3)
    draw.text((F.MARGIN, foot + 22), "PPI is the cut-out subject's at a 3 in order; amber = under the 300 PPI target "
              "(the prefixed subjects are often smaller in the frame).", font=F.font(14), fill=F.INK_3)
    return canvas


# --- main ------------------------------------------------------------------------------------------


def resolve(images: dict[str, F.RealImage], ident: str) -> F.RealImage:
    return F.resolve(images, ident)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--realset-split", default="test")
    ap.add_argument("--bench-split", default="test")
    ap.add_argument("-o", "--out", type=Path, default=Path("docs/img"))
    ap.add_argument("--hero", required=True, help="sha256 prefix of a die-cut image whose rules proof was accepted")
    ap.add_argument("--gallery", nargs=6, required=True, metavar="ID")
    ap.add_argument("--prefix", nargs="+", default=None, metavar="PROMPT_ID",
                    help="prompt ids for prefix-strip.png (scene as typed, die-cut with the prefix)")
    ap.add_argument("--root", type=Path, default=Path("."))
    args = ap.parse_args(argv)
    root, out = args.root, args.out
    rules = final_runs(root, args.realset_split, "rules")
    verdicts = pass2_verdicts(root, args.realset_split)
    hero_im = resolve(rules, args.hero)
    if (hero_im.run.get("shape") or "die_cut") != "die_cut" or verdict_for(hero_im, verdicts) != "acceptable":
        raise SystemExit(f"hero {args.hero}: needs a die-cut rules proof Ebin accepted in pass 2")
    written = [F.save(hero(hero_im), out / "hero.png")]
    picks = [resolve(rules, i) for i in args.gallery]
    written.append(F.save(gallery(picks, verdicts), out / "gallery-strip.png"))
    written.append(F.save(outcomes(root, args.realset_split), out / "outcomes.png"))
    metrics = json.loads((root / "results" / "bench" / args.bench_split / "metrics.json").read_text(encoding="utf-8"))
    written.append(F.save(F.bench_heat(metrics), out / "bench-heat.png"))
    written.append(F.save(results(root, args.realset_split), out / "results.png"))
    if args.prefix:
        written.append(F.save(prefix_strip(root, args.prefix, args.realset_split), out / "prefix-strip.png"))
    print(f"hero: {hero_im.prompt_id} {hero_im.model_short} {hero_im.sha[:12]}")
    print("gallery: " + ", ".join(f"{p.prompt_id}/{p.model_short} {p.sha[:8]} ({verdict_for(p, verdicts)})"
                                  for p in picks))
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
