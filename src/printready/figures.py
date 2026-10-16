"""README figures, rebuilt from saved results so none of them is hand-made.

- hero.png          one real image: generated | what the checks found | the proof (cut line, border)
- gallery-strip.png six before/after pairs with their outcomes
- bench-heat.png    the planted-defect benchmark as one table (results/bench/<split>/metrics.json)
- outcomes.png      ready / fixable / needs a person per image model (and mode), real set

Everything is drawn with Pillow in DejaVu Sans on the project's paper palette (the web UI's design
tokens), at 1600 px wide: about twice the README column, so it stays crisp on high-density screens.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from printready.realset import Paths

WIDTH = 1600
MARGIN = 48
GUTTER = 32

# Design tokens (src/printready/web/static/css/tokens.css, light theme).
PAPER = "#f4f2ed"
SURFACE = "#ffffff"
LINE = "#e3dfd6"
LINE_STRONG = "#cec8bc"
INK = "#17171c"
INK_2 = "#45454d"
INK_3 = "#66656d"
INK_4 = "#9a98a0"
CUT = "#e4007c"
CHECKER = ("#ffffff", "#eae7e0")
STATUS = {  # background, ink, dot
    "pass": ("#e2f3e8", "#13693a", "#1f9d57"),
    "warn": ("#fbefd6", "#874e00", "#d98e04"),
    "fail": ("#fbe4e1", "#b42318", "#e0402f"),
    "skip": ("#eeede9", "#56555d", "#a19fa6"),
}
OUTCOME = {  # background, ink, solid (bars)
    "ready": ("#e5f4eb", "#0f5c32", "#1f9d57"),
    "fixable": ("#fce8f3", "#9a0059", "#d4007a"),
    "needs_person": ("#fcf0d9", "#774400", "#d98e04"),
}
OUTCOME_LABEL = {"ready": "ready", "fixable": "fixable", "needs_person": "needs a person"}
FIX_WORDS = {"remove_background": "background removed", "pad_canvas": "space added at the edges",
             "bridge_islands": "parts joined", "add_border": "border and cut line added"}


# --- drawing helpers ------------------------------------------------------------------------------


@lru_cache(maxsize=64)
def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(str(Path(matplotlib.get_data_path()) / "fonts" / "ttf" / name), size)


def text_width(text: str, f: ImageFont.FreeTypeFont) -> float:
    return f.getlength(text)


def ellipsize(text: str, f: ImageFont.FreeTypeFont, max_w: float) -> str:
    if text_width(text, f) <= max_w:
        return text
    while text and text_width(text + "…", f) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: float, max_lines: int = 2) -> list[str]:
    """Greedy word wrap; the last line is ellipsized if the text does not fit."""
    lines: list[str] = []
    words = text.split()
    while words and len(lines) < max_lines:
        line = words.pop(0)
        while words and text_width(line + " " + words[0], f) <= max_w:
            line += " " + words.pop(0)
        lines.append(line)
    if words:
        lines[-1] = ellipsize(lines[-1] + " " + " ".join(words), f, max_w)
    return lines


def chip(draw: ImageDraw.ImageDraw, x: float, y: float, text: str, bg: str, ink: str, *, size: int = 15,
         dot: str | None = None, bold: bool = True) -> float:
    """A pill label with an optional status dot; returns its width."""
    f = font(size, bold)
    pad_x, h = 10, size + 12
    dot_w = (size * 0.55 + 7) if dot else 0
    w = text_width(text, f) + 2 * pad_x + dot_w
    draw.rounded_rectangle([x, y, x + w, y + h], radius=h / 2, fill=bg)
    if dot:
        r = size * 0.275
        cx, cy = x + pad_x + r, y + h / 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=dot)
    draw.text((x + pad_x + dot_w, y + h / 2), text, font=f, fill=ink, anchor="lm")
    return w


def checkerboard(w: int, h: int, cell: int = 12) -> Image.Image:
    yy, xx = np.mgrid[0:h, 0:w]
    board = ((yy // cell + xx // cell) % 2).astype(bool)
    a, b = (np.array(Image.new("RGB", (1, 1), c)).reshape(3) for c in CHECKER)
    return Image.fromarray(np.where(board[..., None], b, a).astype(np.uint8))


def fit(im: Image.Image, w: int, h: int) -> Image.Image:
    """Scaled (Lanczos) to fit inside w x h, aspect kept."""
    k = min(w / im.width, h / im.height)
    return im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.Resampling.LANCZOS)


def card(canvas: Image.Image, box: tuple[int, int, int, int], im: Image.Image, *, pad: int = 0) -> tuple[int, int, float]:
    """Paste `im` centred in a white rounded card; returns (x, y, scale) of the pasted image."""
    draw = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=12, fill=SURFACE, outline=LINE, width=1)
    inner = fit(im, x1 - x0 - 2 * pad, y1 - y0 - 2 * pad)
    x = x0 + (x1 - x0 - inner.width) // 2
    y = y0 + (y1 - y0 - inner.height) // 2
    mask = Image.new("L", inner.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, inner.width - 1, inner.height - 1], radius=10 if not pad else 6,
                                           fill=255)
    canvas.paste(inner.convert("RGB"), (x, y), mask)
    return x, y, inner.width / im.width


def cut_paths(out_dir: Path) -> list[list[tuple[float, float]]] | None:
    """The die-cut line from cutline.svg, in pixels of fixed.png (and so of the cropped proof).
    None if there is no cut line or it uses commands other than straight segments."""
    svg, fixed = out_dir / "cutline.svg", out_dir / "fixed.png"
    if not svg.exists() or not fixed.exists():
        return None
    text = svg.read_text(encoding="utf-8")
    vb = re.search(r'viewBox="\s*([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*"', text)
    if not vb:
        return None
    vx, vy, vw, _ = (float(v) for v in vb.groups())
    with Image.open(fixed) as im:
        k = im.width / vw
    paths: list[list[tuple[float, float]]] = []
    for d in re.findall(r'<path[^>]*\sd="([^"]+)"', text):
        tokens = re.findall(r"[A-Za-z]|-?\d*\.?\d+(?:[eE][-+]?\d+)?", d)
        current: list[tuple[float, float]] = []
        i = 0
        while i < len(tokens):
            t = tokens[i]
            if t in "ML":
                if t == "M" and current:
                    paths.append(current)
                    current = []
                current.append(((float(tokens[i + 1]) - vx) * k, (float(tokens[i + 2]) - vy) * k))
                i += 3
            elif t in "Zz":
                if current:
                    current.append(current[0])
                    paths.append(current)
                    current = []
                i += 1
            elif t[0].isalpha():
                return None  # curves are not drawn here
            else:  # implicit L after a coordinate pair
                current.append(((float(t) - vx) * k, (float(tokens[i + 1]) - vy) * k))
                i += 2
        if current:
            paths.append(current)
    return paths or None


def draw_cut(canvas: Image.Image, paths, x: float, y: float, k: float, width: float = 2.5) -> None:
    """The cut line, anti-aliased (drawn at 4x and scaled down): magenta over a thin white halo."""
    ss = 4
    xs = [px for path in paths for px, _ in path]
    ys = [py for path in paths for _, py in path]
    x0, y0 = int(x + min(xs) * k) - 8, int(y + min(ys) * k) - 8
    x1, y1 = int(x + max(xs) * k) + 9, int(y + max(ys) * k) + 9
    layer = Image.new("RGBA", ((x1 - x0) * ss, (y1 - y0) * ss), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for colour, w in (("#ffffffc0", width + 3), (CUT, width)):
        for path in paths:
            pts = [((x + px * k - x0) * ss, (y + py * k - y0) * ss) for px, py in path]
            draw.line(pts, fill=colour, width=round(w * ss), joint="curve")
    layer = layer.resize((x1 - x0, y1 - y0), Image.Resampling.LANCZOS)
    base = canvas.crop((x0, y0, x1, y1)).convert("RGBA")
    canvas.paste(Image.alpha_composite(base, layer).convert("RGB"), (x0, y0))


def save(im: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, format="PNG", optimize=True)
    return path


# --- real-set data --------------------------------------------------------------------------------


@dataclass
class RealImage:
    sha: str
    prompt_id: str
    prompt: str
    image_model: str
    original: Path
    run: dict[str, Any]  # the last runs.jsonl line for this image and mode
    out_dir: Path

    @property
    def model_short(self) -> str:
        return self.image_model.split(":")[-1]

    def report(self) -> dict[str, Any]:
        return json.loads((self.out_dir / "report.json").read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def realset_runs(root: Path, split: str, mode: str = "rules") -> dict[str, RealImage]:
    """Last run per image for a mode, joined with the generation manifest, in prompt order."""
    paths = Paths.for_split(split, root)
    manifest = {m["sha256"]: m for m in _jsonl(paths.manifest)}
    last: dict[str, dict[str, Any]] = {}
    for row in _jsonl(paths.runs(mode)):
        last[row["image"]] = row
    out = {}
    for sha, row in sorted(last.items(), key=lambda kv: (kv[1]["prompt_id"], kv[1]["image_model"])):
        m = manifest.get(sha, {})
        out[sha] = RealImage(sha, row["prompt_id"], m.get("prompt", ""), row["image_model"],
                             paths.data / m.get("file", f"images/{sha}.png"), row, root / row["out_dir"])
    return out


def resolve(images: dict[str, RealImage], ident: str) -> RealImage:
    """An image by sha256 prefix (6+ characters) or by "<prompt id>/<image model>"."""
    hits = [im for sha, im in images.items() if sha.startswith(ident.lower())] if len(ident) >= 6 else []
    if "/" in ident:
        pid, model = ident.split("/", 1)
        hits = [im for im in images.values() if im.prompt_id == pid and im.image_model.endswith(model)]
    if len(hits) != 1:
        raise KeyError(f"{ident!r} matches {len(hits)} real-set images; give a longer sha256 prefix")
    return hits[0]


def proof_image(im: RealImage) -> Image.Image:
    """The proof the customer sees (checkerboard, white border, magenta cut line), without its label
    strip: proof.png cropped to the fixed art's size."""
    proof = Image.open(im.out_dir / "proof.png").convert("RGB")
    fixed_path = im.out_dir / "fixed.png"
    if fixed_path.exists():
        with Image.open(fixed_path) as fixed:
            proof = proof.crop((0, 0, fixed.width, min(fixed.height, proof.height)))
    return proof


def short_label(finding: dict[str, Any], size_in: float) -> str | None:
    """A few words for a warn/fail finding (and the PPI, which is always worth showing)."""
    c, m, s = finding["check"], finding.get("measured") or {}, finding["status"]
    if c == "resolution" and m.get("ppi"):
        return f"{m['ppi']:.0f} PPI at {size_in:g} in"
    if s not in ("warn", "fail"):
        return None
    if c == "background":
        if finding["fixer"] == "auto" and m.get("colour_hex"):
            return f"solid {m['colour_hex']} background"
        return "background is not one solid colour"
    if c == "soft_alpha":
        return "soft shadow or glow at the edge"
    if c == "edge_crop":
        return "art touches the edge" if s == "warn" else "art cut off at the edge"
    if c == "islands":
        return f"{m.get('components', 'several')} separate pieces"
    if c == "text_garbled":
        seen = [i.get("seen") for i in m.get("items", []) if i.get("garbled")]
        return f'garbled text "{seen[0]}"' if seen else "garbled text"
    if c == "text_small":
        return f"text about {m['min_text_pt_equiv']:.0f} pt" if m.get("min_text_pt_equiv") else "text too small"
    if c == "file":
        return "file cannot be used"
    return c.replace("_", " ")


def background_mask(im: RealImage, report: dict[str, Any], shape: tuple[int, int]) -> np.ndarray | None:
    """Pixels of the original that background removal took away (from fixed.png and the pad offset)."""
    if not any(s["fix"] == "remove_background" and s["ok"] for s in report.get("history", [])):
        return None
    with Image.open(im.out_dir / "fixed.png") as fixed:
        alpha = np.asarray(fixed.convert("RGBA"))[..., 3]
    dx, dy = (report.get("art") or {}).get("offset", [0, 0])
    h, w = shape
    sub = alpha[dy:dy + h, dx:dx + w]
    if sub.shape != (h, w):
        return None
    return sub == 0


# --- hero -----------------------------------------------------------------------------------------


def _steps_text(report: dict[str, Any]) -> str:
    done = [FIX_WORDS.get(s["fix"], s["fix"]) for s in report.get("history", []) if s["ok"]]
    return ", ".join(done) if done else "no changes"


def hero(im: RealImage, size_in: float = 3.0) -> Image.Image:
    report = im.report()
    panel = (WIDTH - 2 * MARGIN - 2 * GUTTER) // 3
    title_h, caption_h = 44, 64
    height = MARGIN + title_h + panel + caption_h + MARGIN - 8
    canvas = Image.new("RGB", (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(canvas)
    original = Image.open(im.original).convert("RGB")
    xs = [MARGIN + k * (panel + GUTTER) for k in range(3)]
    top = MARGIN + title_h
    titles = [f"Generated by {im.model_short}", "What the checks found", "Proof for the customer"]
    for k, (x, title) in enumerate(zip(xs, titles)):
        draw.text((x, MARGIN + 6), str(k + 1), font=font(20, True), fill=CUT, anchor="lt")
        draw.text((x + 24, MARGIN + 6), title, font=font(20, True), fill=INK, anchor="lt")

    # 1: as generated
    card(canvas, (xs[0], top, xs[0] + panel, top + panel), original)

    # 2: the issues, drawn over the original
    issues = original.convert("RGBA")
    bg = background_mask(im, report, (original.height, original.width))
    if bg is not None:
        tint = Image.new("RGBA", issues.size, STATUS["fail"][2] + "00")
        arr = np.array(tint)
        yy, xx = np.mgrid[0:original.height, 0:original.width]
        hatch = ((xx + yy) // 10) % 3 == 0
        arr[bg] = (224, 64, 47, 70)
        arr[bg & hatch] = (224, 64, 47, 150)
        issues = Image.alpha_composite(issues, Image.fromarray(arr))
    x, y, k = card(canvas, (xs[1], top, xs[1] + panel, top + panel), issues)
    findings = report["before"]["findings"] + [f for f in report["after"]["findings"]
                                               if f["check"].startswith("text_")]
    for f in findings:
        for bx0, by0, bx1, by1 in f.get("boxes", []):
            draw.rectangle([x + bx0 * k, y + by0 * k, x + bx1 * k, y + by1 * k],
                           outline=STATUS.get(f["status"], STATUS["fail"])[2], width=3)
    cy = y + 12
    order = sorted(findings, key=lambda f: {"fail": 0, "warn": 1}.get(f["status"], 2))
    for f in order:
        label = short_label(f, size_in)
        if label:
            bg_c, ink_c, dot_c = STATUS.get(f["status"], STATUS["skip"])
            chip(draw, x + 12, cy, label, bg_c, ink_c, dot=dot_c)
            cy += 36

    # 3: the proof, with the real cut path drawn crisply over it
    px, py, pk = card(canvas, (xs[2], top, xs[2] + panel, top + panel), proof_image(im))
    paths = cut_paths(im.out_dir)
    if paths:
        draw_cut(canvas, paths, px, py, pk)

    # caption: outcome chip + what happened
    outcome = report["outcome"]
    cy = top + panel + 20
    bg_c, ink_c, _ = OUTCOME[outcome]
    w = chip(draw, MARGIN, cy, OUTCOME_LABEL[outcome], bg_c, ink_c, size=16)
    prompt = f"\u201c{im.prompt}\u201d" if im.prompt else im.prompt_id
    text = f"{prompt}  ·  {size_in:g} in die-cut  ·  {report.get('mode', 'rules')} mode: {_steps_text(report)}"
    f = font(17)
    draw.text((MARGIN + w + 14, cy + 14), ellipsize(text, f, WIDTH - 2 * MARGIN - w - 14), font=f, fill=INK_2,
              anchor="lm")
    return canvas


# --- gallery --------------------------------------------------------------------------------------


def gallery(images: list[RealImage]) -> Image.Image:
    cols, rows = 3, 2
    cell_w = (WIDTH - 2 * MARGIN - (cols - 1) * GUTTER) // cols
    thumb = (cell_w - 36) // 2
    cell_h = thumb + 70
    height = 2 * MARGIN + rows * cell_h + (rows - 1) * GUTTER
    canvas = Image.new("RGB", (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(canvas)
    for n, im in enumerate(images[: cols * rows]):
        cx = MARGIN + (n % cols) * (cell_w + GUTTER)
        cy = MARGIN + (n // cols) * (cell_h + GUTTER)
        report = im.report()
        card(canvas, (cx, cy, cx + thumb, cy + thumb), Image.open(im.original).convert("RGB"))
        ax = cx + thumb + 18
        draw.text((ax, cy + thumb / 2), "→", font=font(22, True), fill=INK_4, anchor="mm")
        after_x = cx + thumb + 36
        if report["outcome"] == "needs_person":
            draw.rounded_rectangle([after_x, cy, after_x + thumb, cy + thumb], radius=12, fill=OUTCOME["needs_person"][0],
                                   outline=LINE, width=1)
            reasons = [short_label(f, 3.0) for f in report["after"]["findings"] if f["status"] in ("warn", "fail")]
            reasons = [r for r in reasons if r and "PPI" not in r] or [report.get("handoff_reason") or "a judgment call"]
            lines = wrap(reasons[0], font(14), thumb - 32)
            ty = cy + thumb / 2 - 10 * len(lines) - 4
            draw.text((after_x + thumb / 2, ty), "sent to a person", font=font(16, True),
                      fill=OUTCOME["needs_person"][1], anchor="mm")
            for n_line, line in enumerate(lines):
                draw.text((after_x + thumb / 2, ty + 26 + 19 * n_line), line, font=font(14),
                          fill=OUTCOME["needs_person"][1], anchor="mm")
        else:
            px, py, pk = card(canvas, (after_x, cy, after_x + thumb, cy + thumb), proof_image(im))
            paths = cut_paths(im.out_dir)
            if paths:
                draw_cut(canvas, paths, px, py, pk, width=1.8)
        bg_c, ink_c, _ = OUTCOME[report["outcome"]]
        w = chip(draw, cx, cy + thumb + 12, OUTCOME_LABEL[report["outcome"]], bg_c, ink_c, size=14)
        f = font(14)
        label = im.prompt or im.prompt_id
        draw.text((cx + w + 10, cy + thumb + 25), ellipsize(label, f, cell_w - w - 10), font=f, fill=INK_2,
                  anchor="lm")
        detail = ellipsize(f"{im.model_short}  ·  {_steps_text(report)}", font(12), cell_w)
        draw.text((cx, cy + thumb + 52), detail, font=font(12), fill=INK_3, anchor="lm")
    return canvas


# --- benchmark table ------------------------------------------------------------------------------


def _bench_rows(metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """One row per check: planted defects, recall, precision, false flags, fixer agreement."""
    flagged = ("warn", "fail")
    rows = []
    for check, m in metrics["checks"].items():
        mat = m["matrix"]
        pred_flag = [j for j, c in enumerate(mat["cols"]) if c in flagged]
        tp = sum(sum(mat["counts"][i][j] for j in pred_flag) for i, r in enumerate(mat["rows"]) if r in flagged)
        fp = sum(sum(mat["counts"][i][j] for j in pred_flag) for i, r in enumerate(mat["rows"]) if r not in flagged)
        n = m.get("n_expected_flagged", tp)
        cf, fx = m.get("clean_false_flags", {}), m.get("fixer_pairs", {})
        rows.append({"check": check, "kind": "deterministic", "n": n,
                     "recall": (m.get("recall"), f"{round((m.get('recall') or 0) * n)}/{n}" if n else ""),
                     "precision": ((tp / (tp + fp)) if tp + fp else None, f"{tp}/{tp + fp}" if tp + fp else ""),
                     "false": ((cf["flagged"] / cf["n"]) if cf.get("n") else None,
                               f"{cf.get('flagged', 0)}/{cf.get('n', 0)}"),
                     "fixer": (m.get("fixer_agreement"), f"{fx.get('agree', 0)}/{fx.get('n', 0)}" if fx.get("n") else "")})
    for check in ("text_garbled", "text_small"):
        v = (metrics.get("vision") or {}).get(check)
        if not v or v.get("disabled"):
            continue
        tp, fp, fn, tn = v["tp"], v["fp"], v["fn"], v["tn"]
        rows.append({"check": check, "kind": "vision", "n": tp + fn,
                     "recall": (v["recall"], f"{tp}/{tp + fn}"),
                     "precision": (v["precision"], f"{tp}/{tp + fp}" if tp + fp else ""),
                     "false": ((fp / (fp + tn)) if fp + tn else None, f"{fp}/{fp + tn}"),
                     "fixer": (None, "")})
    return rows


def _grade(value: float | None, higher_is_better: bool = True) -> str:
    if value is None:
        return "skip"
    if higher_is_better:
        return "pass" if value >= 0.95 else "warn" if value >= 0.80 else "fail"
    return "pass" if value <= 0.05 else "warn" if value <= 0.15 else "fail"


def bench_heat(metrics: dict[str, Any]) -> Image.Image:
    rows = _bench_rows(metrics)
    cols = [("recall", "Recall", True), ("precision", "Precision", True),
            ("false", "False flags", False), ("fixer", "Fixer agrees", True)]
    label_w, n_w, cell_w, row_h = 300, 150, 230, 54
    table_w = label_w + n_w + len(cols) * cell_w
    x0 = (WIDTH - table_w) // 2
    head_y = MARGIN + 76
    height = head_y + 44 + len(rows) * row_h + 24 + 100 + MARGIN
    canvas = Image.new("RGB", (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(canvas)
    split, n = metrics.get("split", "?"), metrics.get("n", 0)
    draw.text((x0, MARGIN), f"Planted-defect benchmark, {split} split", font=font(26, True), fill=INK)
    cost = (metrics.get("vision") or {}).get("cost_usd")
    sub = f"{n} generated images with known defects; checks on the image as given"
    if metrics.get("vision"):
        sub += f"; vision rows: live {metrics['vision'].get('model', '')} on the text samples"
        sub += f" (${cost:.2f})" if cost is not None else ""
    draw.text((x0, MARGIN + 38), sub, font=font(16), fill=INK_3)
    heads = [("Check", label_w), ("Defects", n_w)] + [(c[1], cell_w) for c in cols]
    hx = x0
    for text, w in heads:
        draw.text((hx + (12 if text == "Check" else w / 2), head_y + 20), text, font=font(15, True), fill=INK_2,
                  anchor="lm" if text == "Check" else "mm")
        hx += w
    y = head_y + 44
    draw.line([x0, y - 2, x0 + table_w, y - 2], fill=LINE_STRONG, width=2)
    for r in rows:
        if r["kind"] == "vision" and r is next(q for q in rows if q["kind"] == "vision"):
            draw.line([x0, y, x0 + table_w, y], fill=LINE_STRONG, width=2)
        draw.text((x0 + 12, y + row_h / 2), r["check"].replace("_", " "), font=font(17, True), fill=INK,
                  anchor="lm")
        if r["kind"] == "vision":
            tag_x = x0 + 12 + text_width(r["check"].replace("_", " "), font(17, True)) + 10
            draw.text((tag_x, y + row_h / 2), "vision", font=font(13), fill=INK_4, anchor="lm")
        draw.text((x0 + label_w + n_w / 2, y + row_h / 2), str(r["n"]), font=font(17), fill=INK_2, anchor="mm")
        cx = x0 + label_w + n_w
        for key, _, better_high in cols:
            value, detail = r[key]
            bg_c, ink_c, _ = STATUS[_grade(value, better_high)]
            draw.rounded_rectangle([cx + 6, y + 6, cx + cell_w - 6, y + row_h - 6], radius=8, fill=bg_c)
            if value is None:
                draw.text((cx + cell_w / 2, y + row_h / 2), "n/a", font=font(16), fill=INK_4, anchor="mm")
            else:
                draw.text((cx + cell_w / 2 - 6, y + row_h / 2), f"{100 * value:.0f}%", font=font(18, True), fill=ink_c,
                          anchor="rm")
                draw.text((cx + cell_w / 2 + 6, y + row_h / 2), detail, font=font(14), fill=ink_c, anchor="lm")
            cx += cell_w
        y += row_h
    y += 20
    lx = x0
    for grade, text in (("pass", "meets the preregistered bar (recall, precision, agreement >= 95 %; "
                                 "false flags <= 5 %)"),):
        bg_c, ink_c, dot_c = STATUS[grade]
        lx += chip(draw, lx, y, "green", bg_c, ink_c, size=13, dot=dot_c) + 8
        draw.text((lx, y + 12), text, font=font(14), fill=INK_3, anchor="lm")
    y += 32
    lx = x0
    for grade, word in (("warn", "amber"), ("fail", "red")):
        bg_c, ink_c, dot_c = STATUS[grade]
        lx += chip(draw, lx, y, word, bg_c, ink_c, size=13, dot=dot_c) + 8
    draw.text((lx, y + 12), "below the bar (amber >= 80 %)  ·  false flags: clean images for the deterministic "
              "checks, text samples without the defect for vision", font=font(14), fill=INK_3, anchor="lm")
    off = [c for c, v in (metrics.get("vision") or {}).items() if isinstance(v, dict) and v.get("disabled")]
    if off:
        draw.text((x0, y + 40), f"{', '.join(c.replace('_', ' ') for c in off)}: {v_note(metrics, off[0])}",
                  font=font(14), fill=INK_3, anchor="lm")
    return canvas


def v_note(metrics: dict[str, Any], check: str) -> str:
    return metrics["vision"][check].get("note", "disabled")


# --- outcome bars ---------------------------------------------------------------------------------


def outcome_counts(root: Path, split: str) -> list[tuple[str, str, dict[str, int]]]:
    """(mode, image model, counts per outcome) for every mode with runs."""
    out = []
    for mode in ("rules", "agent"):
        by_model: dict[str, dict[str, int]] = {}
        for im in realset_runs(root, split, mode).values():
            counts = by_model.setdefault(im.image_model, {o: 0 for o in OUTCOME})
            counts[im.run["outcome"]] = counts.get(im.run["outcome"], 0) + 1
        for model in sorted(by_model):
            out.append((mode, model, by_model[model]))
    return out


def outcomes_figure(root: Path, split: str) -> Image.Image:
    data = outcome_counts(root, split)
    label_w, bar_h, gap = 360, 46, 22
    bar_x0, bar_x1 = MARGIN + label_w, WIDTH - MARGIN - 90
    height = MARGIN + 110 + len(data) * (bar_h + gap) + MARGIN
    canvas = Image.new("RGB", (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(canvas)
    draw.text((MARGIN, MARGIN), f"Real images, {split} split: outcome at a 3 in die-cut order", font=font(26, True),
              fill=INK)
    draw.text((MARGIN, MARGIN + 38), "Share of images per image model and mode; numbers are image counts.",
              font=font(16), fill=INK_3)
    lx = MARGIN
    for o in OUTCOME:
        draw.rounded_rectangle([lx, MARGIN + 76, lx + 18, MARGIN + 94], radius=4, fill=OUTCOME[o][2])
        draw.text((lx + 26, MARGIN + 85), OUTCOME_LABEL[o], font=font(15), fill=INK_2, anchor="lm")
        lx += 26 + text_width(OUTCOME_LABEL[o], font(15)) + 28
    y = MARGIN + 120
    modes = {m for m, _, _ in data}
    for mode, model, counts in data:
        total = sum(counts.values())
        label = model.split(":")[-1] + (f"  ·  {mode}" if len(modes) > 1 else "")
        draw.text((MARGIN, y + bar_h / 2), label, font=font(17, True), fill=INK, anchor="lm")
        x = bar_x0
        for o in OUTCOME:
            n = counts.get(o, 0)
            if not n:
                continue
            w = (bar_x1 - bar_x0) * n / total
            draw.rounded_rectangle([x + 1, y, x + w - 1, y + bar_h], radius=4, fill=OUTCOME[o][2])  # 2 px gaps
            ink = INK if o == "needs_person" else "#ffffff"
            if w > 40:
                draw.text((x + w / 2, y + bar_h / 2), str(n), font=font(17, True), fill=ink, anchor="mm")
            x += w
        draw.text((bar_x1 + 14, y + bar_h / 2), f"n = {total}", font=font(15), fill=INK_3, anchor="lm")
        y += bar_h + gap
    return canvas


# --- building all of them -------------------------------------------------------------------------


def default_hero(images: dict[str, RealImage]) -> RealImage:
    """The first fixable image whose fixes include background removal (a visible change)."""
    for im in images.values():
        if im.run["outcome"] == "fixable" and any(
                (s.get("fix") if isinstance(s, dict) else s) == "remove_background" for s in im.run.get("steps", [])):
            return im
    return next(iter(images.values()))


def default_gallery(images: dict[str, RealImage], n: int = 6) -> list[RealImage]:
    """Alternate fixable and needs-a-person images in prompt order, one per prompt where possible."""
    pools = {o: [im for im in images.values() if im.run["outcome"] == o] for o in OUTCOME}
    picked, used = [], set()
    order = ["fixable", "needs_person", "ready"]
    while len(picked) < n and any(pools[o] for o in order):
        for o in order:
            pool = [im for im in pools[o] if im.prompt_id not in used] or pools[o]
            if pool and len(picked) < n:
                im = pool[0]
                pools[o].remove(im)
                picked.append(im)
                used.add(im.prompt_id)
    return picked


def build_all(root: Path | str, out: Path | str, *, realset_split: str = "dev", bench_split: str = "dev",
              hero_id: str | None = None, gallery_ids: list[str] | None = None, mode: str = "rules",
              log=print) -> list[Path]:
    root, out = Path(root), Path(out)
    written = []
    images = realset_runs(root, realset_split, mode)
    if images:
        im = resolve(images, hero_id) if hero_id else default_hero(images)
        written.append(save(hero(im), out / "hero.png"))
        log(f"  hero: {im.prompt_id} {im.model_short} {im.sha[:12]}")
        picks = [resolve(images, i) for i in gallery_ids] if gallery_ids else default_gallery(images)
        written.append(save(gallery(picks), out / "gallery-strip.png"))
        log("  gallery: " + ", ".join(f"{p.prompt_id}/{p.model_short} {p.sha[:8]}" for p in picks))
        written.append(save(outcomes_figure(root, realset_split), out / "outcomes.png"))
    else:
        log(f"  no real-set runs for the {realset_split} split: hero, gallery and outcomes skipped")
    metrics_path = root / "results" / "bench" / bench_split / "metrics.json"
    if metrics_path.exists():
        written.append(save(bench_heat(json.loads(metrics_path.read_text(encoding="utf-8"))), out / "bench-heat.png"))
    else:
        log(f"  {metrics_path} not found: bench-heat skipped")
    return written
