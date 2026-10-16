"""EXPLORATORY, POST HOC, ONE MODEL, ONE PREFIX; NOT PREREGISTERED.

Question: does a short sticker-style prefix stop Grok Imagine from returning scenes?

Fixed before any image was generated (17 Oct 2026):
    PREFIX = "Die-cut sticker design, single subject, flat plain white background, no scenery, no shadow: "
    model  = xai:grok-imagine-image ($0.02 per image), one image per prompt
    prompts = the 50 test prompts in realset/prompts.txt (p01..p50), PREFIX + prompt
    judged by rules mode, deterministic only (pipeline.run_rules with client=None: no vision call)

Compared with the SAME model's unprefixed test images, rules mode, original (preregistered) runs.
The product each run ends with is deterministic: a die-cut (background removed) or a whole-image
rounded rectangle (fit_shape: a scene). Text checks are not part of this comparison.

    uv run python analysis/prompt_prefix.py            # estimate only
    uv run python analysis/prompt_prefix.py --yes      # generate (resumable), run rules, report

Writes data/realset/prefix/{manifest.jsonl,images/} (images gitignored) and
results/realset/prefix/{runs.jsonl,contact-sheet.jpg,prefix.md}. Uses public APIs only
(printready.llm.generate_image, printready.pipeline.run_rules, printready.realset helpers).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from printready.llm import generate_image
from printready.pipeline import run_rules
from printready.profile import load_profile
from printready.realset import append_jsonl, last_by, load_prompts, read_jsonl, spec_for
from printready.realset.runs import summarize
from printready.spend import ledger_total, price_for, repo_root

PREFIX = "Die-cut sticker design, single subject, flat plain white background, no scenery, no shadow: "
MODEL = "xai:grok-imagine-image"
MAX_USD = 1.10
CAVEAT = "Exploratory, post hoc, one model, one prefix; not preregistered."
PRODUCTS = ("die_cut", "rounded_rect", "needs_person")
EXTENSIONS = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp"}


def product(row: dict[str, Any]) -> str:
    """The product the deterministic path ended with; needs_person only for non-text reasons
    (the prefixed runs have no vision check, so text findings are left out on both sides)."""
    if _person_reasons(row):
        return "needs_person"
    return row.get("shape") or "die_cut"


def _person_reasons(row: dict[str, Any]) -> list[str]:
    return sorted(k for k, v in row["after"].items() if not k.startswith("text_")
                  and v["status"] in ("warn", "fail", "skip") and v["fixer"] in ("person", "none", "auto"))


# ---------------------------------------------------------------- generate and run

def generate(root: Path, model: str, max_usd: float, gen: Callable[..., bytes] = generate_image,
             log: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """One image per test prompt with the prefix; resumable; stops before passing max_usd."""
    data = root / "data" / "realset" / "prefix"
    (data / "images").mkdir(parents=True, exist_ok=True)
    manifest = read_jsonl(data / "manifest.jsonl")
    done = {e["prompt_id"] for e in manifest if (data / e["file"]).exists()}
    spent = sum(e["cost_usd"] for e in manifest)
    per_image = price_for(model).per_image
    new = []
    for pid, prompt in load_prompts(root / "realset" / "prompts.txt", "p"):
        if pid in done:
            continue
        if spent + per_image > max_usd + 1e-9:
            log(f"  stopping: the next image would pass ${max_usd:.2f} (spent ${spent:.2f})")
            break
        raw = gen(model, PREFIX + prompt, purpose="prefix-experiment")
        sha = hashlib.sha256(raw).hexdigest()
        with Image.open(io.BytesIO(raw)) as im:
            fmt, (w, h) = im.format or "PNG", im.size
        rel = f"images/{sha}.{EXTENSIONS.get(fmt, 'png')}"
        (data / rel).write_bytes(raw)
        entry = {"prompt_id": pid, "prompt": prompt, "full_prompt": PREFIX + prompt, "model": model, "sha256": sha,
                 "file": rel, "bytes": len(raw), "width": w, "height": h, "format": fmt, "cost_usd": per_image,
                 "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        append_jsonl(data / "manifest.jsonl", [entry])
        new.append(entry)
        spent += per_image
        log(f"  {pid}: {w}x{h} {fmt} {sha[:12]}")
    return new


def run_all(root: Path, log: Callable[[str], None] = print) -> list[dict[str, Any]]:
    """Rules mode, deterministic only, on every prefixed image not run yet."""
    data, results = root / "data" / "realset" / "prefix", root / "results" / "realset" / "prefix"
    done = set(last_by(read_jsonl(results / "runs.jsonl"), "image"))
    profile, rows = load_profile(), []
    for e in last_by(read_jsonl(data / "manifest.jsonl"), "sha256").values():
        if e["sha256"] in done:
            continue
        out_dir = results / e["sha256"]
        run = run_rules(data / e["file"], spec_for(e["prompt"]), profile, out_dir, client=None)
        row = summarize(run, e, out_dir, root, None)
        append_jsonl(results / "runs.jsonl", [row])
        rows.append(row)
        log(f"  {e['prompt_id']}: {row['outcome']} {row['shape']}")
    return rows


# ---------------------------------------------------------------- report

def compare(root: Path, model: str = MODEL) -> dict[str, Any]:
    prefixed = last_by(read_jsonl(root / "results" / "realset" / "prefix" / "runs.jsonl"), "prompt_id")
    original = {r["prompt_id"]: r for r in last_by(read_jsonl(root / "results" / "realset" / "test" / "rules" / "runs.jsonl"),
                                                   "image").values() if r["image_model"] == model}
    both = sorted(set(prefixed) & set(original))
    sides = {"unprefixed (test, rules, original runs)": original, "prefixed": prefixed}
    counts = {name: Counter(product(rows[p]) for p in both) for name, rows in sides.items()}
    reasons = {name: Counter(", ".join(_person_reasons(rows[p])) for p in both if product(rows[p]) == "needs_person")
               for name, rows in sides.items()}
    moves = Counter((product(original[p]), product(prefixed[p])) for p in both)
    text_errors = sum(1 for p in both if original[p]["after"].get("text_garbled", {}).get("status") == "skip")
    resolution = {name: Counter(rows[p]["after"]["resolution"]["status"] for p in both) for name, rows in sides.items()}
    return {"n": len(both), "counts": counts, "reasons": reasons, "moves": moves, "text_errors_unprefixed": text_errors,
            "resolution": resolution}


def contact_sheet(root: Path) -> Path:
    data, results = root / "data" / "realset" / "prefix", root / "results" / "realset" / "prefix"
    manifest = last_by(read_jsonl(data / "manifest.jsonl"), "sha256")
    rows = sorted(last_by(read_jsonl(results / "runs.jsonl"), "image").values(), key=lambda r: r["prompt_id"])
    thumb, cols, text_h = 180, 5, 40
    cell_w, cell_h = 2 * thumb + 24, thumb + text_h + 12
    sheet = Image.new("RGB", (cols * cell_w, 50 + max(1, -(-len(rows) // cols)) * cell_h), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=15)
    draw.text((10, 14), f"prefixed {MODEL}, rules mode, 3 in sticker: original | proof. {CAVEAT}", fill="black", font=font)
    for i, row in enumerate(rows):
        x, y = (i % cols) * cell_w + 8, 50 + (i // cols) * cell_h
        for j, path in enumerate((data / manifest[row["image"]]["file"], root / row["out_dir"] / "proof.png")):
            if path.exists():
                with Image.open(path) as im:
                    im = im.convert("RGB")
                    im.thumbnail((thumb, thumb))
                    sheet.paste(im, (x + j * (thumb + 6), y))
        draw.text((x, y + thumb + 4), f"{row['prompt_id']}  {product(row).replace('_', ' ')}", fill="black", font=font)
    out = results / "contact-sheet.jpg"
    sheet.save(out, quality=82)
    return out


def render(c: dict[str, Any], cost: float) -> str:
    names = list(c["counts"])
    lines = [
        "# Does a sticker-style prompt prefix stop Grok Imagine from returning scenes?",
        "",
        f"**{CAVEAT}** Decided after the test results were in. Nothing here changes the preregistered numbers.",
        "",
        f"- Prefix: `{PREFIX}` + the customer's prompt",
        f"- Model: `{MODEL}`, one image per prompt, the {c['n']} test prompts; cost ${cost:.2f}",
        "- Judged by rules mode, deterministic only (no vision call): the product a run ends with is a die-cut "
        "(plain background removed) or a whole-image rounded rectangle (`fit_shape`: no plain background, a scene).",
        "- Compared with the same model's unprefixed test images (rules mode, original runs). Text checks are left out "
        f"on both sides; {c['text_errors_unprefixed']} unprefixed runs had a failed vision call, which does not change "
        "their product.",
        "",
        "| product (exploratory, post hoc) | " + " | ".join(names) + " |",
        "|---|" + "---|" * len(names),
    ]
    for p in PRODUCTS:
        lines.append(f"| {p.replace('_', ' ')} | " + " | ".join(
            f"{c['counts'][n][p]} ({c['counts'][n][p] / max(c['n'], 1):.0%})" for n in names) + " |")
    lines += ["", "Per prompt, unprefixed -> prefixed (exploratory, post hoc):", "", "| move | prompts |", "|---|---|"]
    for (a, b), k in sorted(c["moves"].items(), key=lambda t: -t[1]):
        lines.append(f"| {a.replace('_', ' ')} -> {b.replace('_', ' ')} | {k} |")
    lines += ["", "Resolution at 3 in (exploratory, post hoc): the prefix gives smaller subjects on more white space, "
              "so more die-cuts fall under 300 PPI (warn: the customer picks a smaller size; a rounded rectangle "
              "uses the whole canvas):", "", "| resolution | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for status in ("pass", "warn", "fail"):
        lines.append(f"| {status} | " + " | ".join(str(c["resolution"][n][status]) for n in names) + " |")
    lines += ["", "Why runs needed a person (non-text findings; exploratory, post hoc):", "",
              "| side | reasons |", "|---|---|"]
    for n in names:
        lines.append(f"| {n} | " + (", ".join(f"{r} {k}" for r, k in c["reasons"][n].most_common()) or "none") + " |")
    lines += ["", "Contact sheet: `contact-sheet.jpg` (original | proof per prompt)."]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None, gen: Callable[..., bytes] = generate_image) -> int:
    ap = argparse.ArgumentParser(description=CAVEAT)
    ap.add_argument("--yes", action="store_true", help="make the paid image calls")
    ap.add_argument("--model", default=MODEL)
    ap.add_argument("--max-usd", type=float, default=MAX_USD)
    ap.add_argument("--root", type=Path, default=None)
    args = ap.parse_args(argv)
    root = args.root or repo_root()
    data = root / "data" / "realset" / "prefix"
    have = {e["prompt_id"] for e in read_jsonl(data / "manifest.jsonl") if (data / e["file"]).exists()}
    todo = [p for p, _ in load_prompts(root / "realset" / "prompts.txt", "p") if p not in have]
    per_image = price_for(args.model).per_image
    print(f"{CAVEAT}\n{len(todo)} images to generate with {args.model}: ${len(todo) * per_image:.2f} "
          f"(stop at ${args.max_usd:.2f}); ledger ${ledger_total():.4f}")
    if todo and not args.yes:
        print("Re-run with --yes to generate.", file=sys.stderr)
        return 2
    generate(root, args.model, args.max_usd, gen=gen)
    run_all(root)
    c = compare(root, args.model)
    cost = sum(e["cost_usd"] for e in read_jsonl(data / "manifest.jsonl"))
    out = root / "results" / "realset" / "prefix" / "prefix.md"
    out.write_text(render(c, cost), encoding="utf-8")
    print(render(c, cost))
    print(f"wrote {out} and {contact_sheet(root)}; ledger ${ledger_total():.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
