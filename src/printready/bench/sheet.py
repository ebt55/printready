"""Contact sheet: a grid of a few samples per family and parameter with short captions, so the art
and its planted defects can be eyeballed in one image."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from printready.bench import text as txt

TILE = 180
CAPTION_H = 60
COLUMNS = 10
GAP = 8
PER_GROUP = {"clean": 3, "resolution": 1, "background": 2, "islands": 2, "soft_alpha": 2,
             "edge_crop": 2, "text": 2}


def _group(row: dict[str, Any]) -> str:
    p = row["param"]
    return {
        "clean": lambda: "",
        "resolution": lambda: f"ppi {p['ppi']}",
        "background": lambda: p["background"],
        "islands": lambda: f"gap {p['gap_in']} in",
        "soft_alpha": lambda: f"ramp {p['ramp_in']} in",
        "edge_crop": lambda: f"case {p['case']}",
        "text": lambda: f"{p['cap_pt']} pt" if p["variant"] == "sized" else p["variant"],
    }[row["family"]]()


def pick(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The first few rows of each (family, parameter) group, in manifest order."""
    counts: dict[tuple[str, str], int] = {}
    chosen = []
    for row in rows:
        key = (row["family"], _group(row))
        sized_text = row["family"] == "text" and row["param"]["variant"] == "sized"
        limit = 1 if sized_text else PER_GROUP[row["family"]]
        if counts.get(key, 0) < limit:
            counts[key] = counts.get(key, 0) + 1
            chosen.append(row)
    return chosen


def _caption(row: dict[str, Any]) -> list[str]:
    p, gt = row["param"], row["gt"]
    detail = {
        "clean": lambda: row["kind"],
        "resolution": lambda: f"ppi {gt['ppi']:.0f}",
        "background": lambda: p["background"],
        "islands": lambda: f"gap {gt['gap_in']:.2f} in",
        "soft_alpha": lambda: f"ramp {gt['ramp_in']:.3f} in {p['style']}",
        "edge_crop": lambda: f"({p['case']}) edge run {gt['edge_run_in']:.2f} in",
        "text": lambda: (f"{p['word']} {gt['cap_height_pt']:.1f} pt" if p["variant"] != "garbled"
                         else f"{p['word']} ({p['intended']})"),
    }[row["family"]]()
    flagged = [f"{c} {v['status']}/{v['fixer']}" for c, v in row["expected"].items()
               if v["status"] in ("warn", "fail")]
    outcome = row.get("outcome_vision", row["outcome"])
    return [row["id"], detail, ", ".join(flagged) or "all pass", f"-> {outcome}"]


def _checkerboard(w: int, h: int, cell: int = 8) -> Image.Image:
    board = Image.new("RGB", (w, h), (236, 236, 236))
    draw = ImageDraw.Draw(board)
    for y in range(0, h, cell):
        for x in range((y // cell) % 2 * cell, w, 2 * cell):
            draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=(206, 206, 206))
    return board


def _tile(path: Path) -> Image.Image:
    with Image.open(path) as im:
        im = im.convert("RGBA")
        im.thumbnail((TILE, TILE), Image.Resampling.LANCZOS)
    board = _checkerboard(im.width, im.height).convert("RGBA")
    board.alpha_composite(im)
    return board.convert("RGB")


def write_contact_sheet(rows: list[dict[str, Any]], root: Path, out: Path) -> Path:
    chosen = pick(rows)
    n_rows = (len(chosen) + COLUMNS - 1) // COLUMNS
    cell_w, cell_h = TILE + GAP, TILE + CAPTION_H + GAP
    sheet = Image.new("RGB", (COLUMNS * cell_w + GAP, n_rows * cell_h + GAP), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    small = txt.font(11.0, bold=False)
    bold = txt.font(11.0, bold=True)
    for k, row in enumerate(chosen):
        x, y = GAP + (k % COLUMNS) * cell_w, GAP + (k // COLUMNS) * cell_h
        tile = _tile(Path(root) / row["image"])
        tx, ty = x + (TILE - tile.width) // 2, y + (TILE - tile.height) // 2
        sheet.paste(tile, (tx, ty))
        draw.rectangle([tx - 1, ty - 1, tx + tile.width, ty + tile.height], outline=(150, 150, 150))
        for line_no, line in enumerate(_caption(row)):
            draw.text((x, y + TILE + 3 + 14 * line_no), line, fill=(20, 20, 20),
                      font=bold if line_no == 0 else small)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, format="PNG", compress_level=9)
    return out
