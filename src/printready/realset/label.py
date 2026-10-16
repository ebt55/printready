"""`realset label`: the item lists for Ebin's two blind labelling passes (the page is the UI's).

label-pass1.json  the sampled originals, by hash, shuffled (seed 7), caption "3 in die-cut sticker"
label-pass2.json  every distinct proof either mode would send a customer (outcome ready or
                  fixable), de-duplicated by the sha256 of fixed.png, shuffled
label-pass2-mapping.json   proof sha -> the (mode, image) runs it came from; read only by eval,
                  never by the label page
Every image the page shows is a PNG copy in label-images/<sha256>.png, so neither a path nor a
file format can reveal the image model or the mode.
Labels go to labels.jsonl (schema in 04-WORKBENCH.md), written by the label page.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any, Callable

from PIL import Image

from printready.realset import MODES, Paths, last_by, read_jsonl, sample_shas, shuffled, write_json

CAPTION = "3 in die-cut sticker"
PASS_KEYS = {
    1: {"1": "ready", "2": "fixable", "3": "needs_person"},
    2: {"y": "acceptable", "n": "unacceptable"},
}


def _shown(paths: Paths, source: Path, sha: str) -> str:
    """A PNG copy of `source` named by `sha`, relative to the label dir."""
    rel = f"label-images/{sha}.png"
    dest = paths.data / rel
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as im:
            im.save(dest, format="PNG")
    return rel


def pass1_items(paths: Paths) -> dict[str, Any]:
    manifest = last_by(read_jsonl(paths.manifest), "sha256")
    items = [{"image": sha, "proof": None, "file": _shown(paths, paths.data / manifest[sha]["file"], sha)}
             for sha in sample_shas(list(manifest.values()))]
    data = {"pass": 1, "caption": CAPTION, "keys": PASS_KEYS[1], "labels": paths.labels.name, "items": shuffled(items)}
    write_json(paths.data / "label-pass1.json", data)
    return data


def pass2_items(paths: Paths) -> dict[str, Any]:
    sampled = set(sample_shas(read_jsonl(paths.manifest)))
    mapping: dict[str, list[dict[str, str]]] = {}
    items: dict[str, dict[str, Any]] = {}
    for mode in MODES:
        for row in last_by(read_jsonl(paths.runs(mode)), "image").values():
            proof_sha = row.get("fixed_sha256")
            if row["image"] not in sampled or row["outcome"] == "needs_person" or not proof_sha:
                continue
            mapping.setdefault(proof_sha, []).append({"mode": mode, "image": row["image"]})
            if proof_sha not in items:
                shown = _shown(paths, paths.root / row["out_dir"] / "proof.png", proof_sha)
                items[proof_sha] = {"image": row["image"], "proof": proof_sha, "file": shown}
    data = {"pass": 2, "caption": CAPTION, "keys": PASS_KEYS[2], "labels": paths.labels.name,
            "items": shuffled(sorted(items.values(), key=lambda i: i["proof"]))}
    write_json(paths.data / "label-pass2.json", data)
    write_json(paths.data / "label-pass2-mapping.json", mapping)
    return data


def serve_labels(paths: Paths, label_pass: int, open_browser: bool = True, port: int | None = None,
                 log: Callable[[str], None] = print, server: Any = None) -> int:
    """Start the workbench in label mode (printready.web, owned by the UI agent), lazily."""
    if server is None:
        try:
            from printready.web import server  # noqa: PLC0415 - optional until the UI lands
        except ImportError as exc:
            log(f"realset label: the workbench is not available ({exc}). Items are in {paths.data}.")
            return 2
    serve = getattr(server, "serve", None)
    params = inspect.signature(serve).parameters if callable(serve) else {}
    if not {"label_dir", "label_pass"} <= set(params):
        log("realset label: printready.web.server.serve(label_dir=..., label_pass=...) is not there yet. "
            f"Items are in {paths.data / f'label-pass{label_pass}.json'}.")
        return 2
    kwargs: dict[str, Any] = {"label_dir": paths.data, "label_pass": label_pass}
    if "open_browser" in params:
        kwargs["open_browser"] = open_browser
    if port and "port" in params:
        kwargs["port"] = port
    serve(**kwargs)
    return 0


def labels_by_pass(path: Path) -> tuple[dict[str, str], dict[str, str]]:
    """({image: pass-1 label}, {proof sha: pass-2 label}); the last line per key wins."""
    pass1: dict[str, str] = {}
    pass2: dict[str, str] = {}
    for row in read_jsonl(path):
        if row.get("pass") == 1:
            pass1[row["image"]] = row["label"]
        elif row.get("pass") == 2 and row.get("proof"):
            pass2[row["proof"]] = row["label"]
    return pass1, pass2
