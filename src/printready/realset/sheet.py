"""`realset sheet`: PNG sheets for looking at results (dev split); never for labelling.

contact_sheet:  per image, original | proof | outcome and the flagged findings (one mode)
compare_sheet:  per image, original | rules proof + outcome | agent proof + outcome and handoff
                reason; a magenta bar marks images where the two modes disagree
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from printready.realset import Paths, last_by, read_jsonl

THUMB = 260
TEXT_W = 430
PAD = 12
COLUMNS = 2
OUTCOME_COLOURS = {"ready": (20, 130, 60), "fixable": (190, 0, 110), "needs_person": (190, 110, 0)}
DISAGREE = (228, 0, 124)


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _thumb(path: Path, size: int = THUMB) -> Image.Image:
    tile = Image.new("RGB", (size, size), (235, 235, 235))
    if path.exists():
        with Image.open(path) as im:
            im = im.convert("RGBA")
            im.thumbnail((size, size))
            tile.paste(im, ((size - im.width) // 2, (size - im.height) // 2), im)
    return tile


def flagged_lines(row: dict) -> list[str]:
    """`check status (fixer)` for every finding that is not a pass, before -> after."""
    lines = []
    for check, after in row["after"].items():
        before = row["before"].get(check)
        if after["status"] == "pass" and (before is None or before["status"] == "pass"):
            continue
        was = f"{before['status']} -> " if before and before["status"] != after["status"] else ""
        lines.append(f"{check}: {was}{after['status']}" + (f" ({after['fixer']})" if after["status"] != "pass" else ""))
    return lines


def _describe(draw: ImageDraw.ImageDraw, x: int, y: int, row: dict | None, width_chars: int = 60) -> None:
    """Outcome (coloured), handoff reason, steps and flagged findings of one run row."""
    big, small = _font(22), _font(15)
    if row is None:
        draw.text((x, y), "not run", fill=(150, 150, 150), font=big)
        return
    draw.text((x, y), row["outcome"].replace("_", " ").upper(), fill=OUTCOME_COLOURS[row["outcome"]], font=big)
    y += 30
    steps = ", ".join(s["fix"] + ("" if s["ok"] else " (refused)" if not s["damaged"] else " (damaged)")
                      for s in row["steps"])
    lines = ["shape: rounded rectangle"] if row.get("shape") == "rounded_rect" else []
    lines += [f"handoff: {row['handoff_reason']}"] if row.get("handoff_reason") else []
    lines += (["steps: " + steps] if steps else []) + flagged_lines(row)
    if row.get("cost_usd"):
        lines.append(f"${row['cost_usd']:.4f}, {row.get('elapsed_s', 0):.0f} s")
    for line in lines:
        for part in textwrap.wrap(line, width_chars) or [""]:
            draw.text((x, y), part, fill=(30, 30, 30), font=small)
            y += 19


def _caption(row_or_entry: dict, entry: dict) -> str:
    model = entry.get("model", row_or_entry.get("image_model", "?")).split(":")[-1].replace("grok-imagine-image", "imagine")
    return f"{entry.get('prompt_id', row_or_entry.get('prompt_id', '?'))}  {model}  {entry.get('width', '?')}x{entry.get('height', '?')}"


def contact_sheet(paths: Paths, mode: str = "rules") -> Path:
    rows = sorted(last_by(read_jsonl(paths.runs(mode)), "image").values(), key=lambda r: (r["prompt_id"], r["image_model"]))
    manifest = last_by(read_jsonl(paths.manifest), "sha256")
    cell_w, cell_h = 2 * THUMB + TEXT_W + 4 * PAD, THUMB + 2 * PAD
    header = 44
    sheet = Image.new("RGB", (COLUMNS * cell_w, header + max(1, -(-len(rows) // COLUMNS)) * cell_h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    counts = {o: sum(r["outcome"] == o for r in rows) for o in OUTCOME_COLOURS}
    draw.text((PAD, 10), f"realset {paths.split}, {mode} mode, 3 in sticker (die-cut or rounded rectangle): {len(rows)} images; "
              + ", ".join(f"{o} {n}" for o, n in counts.items()), fill=(0, 0, 0), font=_font(22))
    for i, row in enumerate(rows):
        x0, y0 = (i % COLUMNS) * cell_w, header + (i // COLUMNS) * cell_h
        entry = manifest.get(row["image"], {})
        sheet.paste(_thumb(paths.data / entry.get("file", "missing")), (x0 + PAD, y0 + PAD))
        sheet.paste(_thumb(paths.root / row["out_dir"] / "proof.png"), (x0 + 2 * PAD + THUMB, y0 + PAD))
        tx = x0 + 3 * PAD + 2 * THUMB
        draw.text((tx, y0 + PAD), _caption(row, entry), fill=(60, 60, 60), font=_font(15))
        _describe(draw, tx, y0 + PAD + 22, row)
        draw.line([(x0, y0 + cell_h - 1), (x0 + cell_w, y0 + cell_h - 1)], fill=(220, 220, 220))
    out = paths.results / ("contact-sheet.png" if mode == "rules" else f"contact-sheet-{mode}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, optimize=True)
    return out


def compare_sheet(paths: Paths, thumb: int = 240, text_w: int = 360) -> Path:
    manifest = last_by(read_jsonl(paths.manifest), "sha256")
    runs = {m: last_by(read_jsonl(paths.runs(m)), "image") for m in ("rules", "agent")}
    shas = sorted(manifest, key=lambda s: (manifest[s]["prompt_id"], manifest[s]["model"]))
    row_h, header = thumb + 2 * PAD, 44
    width = 3 * thumb + 2 * text_w + 7 * PAD
    sheet = Image.new("RGB", (width, header + max(1, len(shas)) * row_h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    both = [s for s in shas if s in runs["rules"] and s in runs["agent"]]
    differ = sum(runs["rules"][s]["outcome"] != runs["agent"][s]["outcome"] for s in both)
    draw.text((PAD, 10), f"realset {paths.split}, 3 in sticker (die-cut or rounded rectangle): original | rules | agent. "
              f"{len(both)} images in both modes, "
              f"{differ} disagree (magenta bar)", fill=(0, 0, 0), font=_font(22))
    chars = max(20, text_w // 8)
    for i, sha in enumerate(shas):
        y0 = header + i * row_h
        entry, rules, agent = manifest[sha], runs["rules"].get(sha), runs["agent"].get(sha)
        if rules and agent and rules["outcome"] != agent["outcome"]:
            draw.rectangle([0, y0 + PAD, 5, y0 + row_h - PAD], fill=DISAGREE)
        x = PAD
        sheet.paste(_thumb(paths.data / entry["file"], thumb), (x, y0 + PAD))
        draw.text((x + 4, y0 + PAD + thumb - 20), _caption(entry, entry), fill=(0, 0, 0), font=_font(14))
        for row in (rules, agent):
            x += thumb + PAD
            proof = paths.root / row["out_dir"] / "proof.png" if row else Path("missing")
            sheet.paste(_thumb(proof, thumb), (x, y0 + PAD))
            x += thumb + PAD
            _describe(draw, x, y0 + PAD, row, chars)
            x += text_w - thumb
        draw.line([(0, y0 + row_h - 1), (width, y0 + row_h - 1)], fill=(220, 220, 220))
    out = paths.results / "contact-sheet-compare.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, optimize=True)
    return out
