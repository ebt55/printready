"""`realset sheet`: one PNG with, per image, original | proof | outcome and the flagged findings.
For looking at how the detectors fare on real Grok output (dev split); never for labelling."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from printready.realset import Paths, last_by, read_jsonl

THUMB = 260
TEXT_W = 430
PAD = 12
COLUMNS = 2
OUTCOME_COLOURS = {"ready": (20, 130, 60), "fixable": (190, 0, 110), "needs_person": (190, 110, 0)}


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _thumb(path: Path) -> Image.Image:
    tile = Image.new("RGB", (THUMB, THUMB), (235, 235, 235))
    if path.exists():
        with Image.open(path) as im:
            im = im.convert("RGBA")
            im.thumbnail((THUMB, THUMB))
            tile.paste(im, ((THUMB - im.width) // 2, (THUMB - im.height) // 2), im)
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


def contact_sheet(paths: Paths, mode: str = "rules") -> Path:
    rows = sorted(last_by(read_jsonl(paths.runs(mode)), "image").values(), key=lambda r: (r["prompt_id"], r["image_model"]))
    manifest = last_by(read_jsonl(paths.manifest), "sha256")
    cell_w, cell_h = 2 * THUMB + TEXT_W + 4 * PAD, THUMB + 2 * PAD
    n_rows = max(1, -(-len(rows) // COLUMNS))
    header = 44
    sheet = Image.new("RGB", (COLUMNS * cell_w, header + n_rows * cell_h), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    big, small = _font(22), _font(15)
    counts = {o: sum(r["outcome"] == o for r in rows) for o in OUTCOME_COLOURS}
    draw.text((PAD, 10), f"realset {paths.split}, {mode} mode, 3 in die-cut: {len(rows)} images; "
              + ", ".join(f"{o} {n}" for o, n in counts.items()), fill=(0, 0, 0), font=big)
    for i, row in enumerate(rows):
        x0, y0 = (i % COLUMNS) * cell_w, header + (i // COLUMNS) * cell_h
        entry = manifest.get(row["image"], {})
        sheet.paste(_thumb(paths.data / entry.get("file", "missing")), (x0 + PAD, y0 + PAD))
        sheet.paste(_thumb(paths.root / row["out_dir"] / "proof.png"), (x0 + 2 * PAD + THUMB, y0 + PAD))
        tx, ty = x0 + 3 * PAD + 2 * THUMB, y0 + PAD
        model = row["image_model"].split(":")[-1].replace("grok-imagine-image", "imagine") or "?"
        draw.text((tx, ty), f"{row['prompt_id']}  {model}  {entry.get('width', '?')}x{entry.get('height', '?')}",
                  fill=(60, 60, 60), font=small)
        draw.text((tx, ty + 22), row["outcome"].replace("_", " ").upper(), fill=OUTCOME_COLOURS[row["outcome"]], font=big)
        y = ty + 54
        steps = ", ".join(s["fix"] + ("" if s["ok"] else " (refused)" if not s["damaged"] else " (damaged)")
                          for s in row["steps"])
        for line in (["steps: " + steps] if steps else []) + flagged_lines(row):
            draw.text((tx, y), line[:60], fill=(30, 30, 30), font=small)
            y += 20
        draw.line([(x0, y0 + cell_h - 1), (x0 + cell_w, y0 + cell_h - 1)], fill=(220, 220, 220))
    out = paths.results / "contact-sheet.png" if mode == "rules" else paths.results / f"contact-sheet-{mode}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, optimize=True)
    return out
