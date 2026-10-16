"""Blind keypress labelling (03-EVAL.md section 2, 04-WORKBENCH.md screen 3).

Pass 1 shows each original image with the caption "3 in die-cut sticker"; keys 1-4 record a fact:
ready_diecut / fixable_diecut / scene / needs_person. Pass 2 shows each distinct proof image only (no caption, no mode,
no message); keys y/n label it acceptable / unacceptable. Images are identified by content hash
and shown in a fixed-seed shuffle, so file names never reach the page.

Storage is `labels.jsonl`, append-only, one line per keypress, and the LAST line per key wins:
    {"ts": "...Z", "pass": 1|2, "image": "<sha256>", "proof": "<sha256>"|null, "label": "..."}
Undo (Backspace) only moves the cursor back; the next keypress appends a row that replaces the
previous label. `realset eval` (K5) reads this schema.

Pass 2 serves the proof picture without the size caption that render_proof draws under it
("3.0 in die-cut, 330 PPI"): the band is cropped when the image is served. The file, its hash,
the label key and the list file are unchanged.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import random
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

# Pass 1 records a fact, not a policy (03-EVAL.md). PREREG maps it to outcomes:
# ready_diecut -> ready, fixable_diecut -> fixable, scene -> fixable (rounded-rectangle offer),
# needs_person -> needs_person.
PASS_LABELS: dict[int, tuple[str, ...]] = {
    1: ("ready_diecut", "fixable_diecut", "scene", "needs_person"),
    2: ("acceptable", "unacceptable"),
}
PASS_KEYS: dict[int, list[dict[str, str]]] = {
    1: [{"key": "1", "label": "ready_diecut", "text": "Ready", "hint": "ready as a die-cut"},
        {"key": "2", "label": "fixable_diecut", "text": "Fixable", "hint": "flat background, border or size"},
        {"key": "3", "label": "scene", "text": "Scene", "hint": "whole-image art, no clean edge"},
        {"key": "4", "label": "needs_person", "text": "Needs a person", "hint": "garbled text, cut off, ambiguous"}],
    2: [{"key": "y", "label": "acceptable", "text": "Acceptable", "hint": "would send this proof"},
        {"key": "n", "label": "unacceptable", "text": "Not acceptable", "hint": "would not send it"}],
}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_SEED = 7
TEXT_DARK = 110  # a caption pixel this dark (every channel) is lettering


# ------------------------------------------------------------------ pass 2: the proof without its caption

def _band_stats(band):
    """(neutral share, white share, dark pixel count) of an RGB pixel block."""
    import numpy as np

    px = band.astype(np.int16)
    spread = px.max(axis=-1) - px.min(axis=-1)
    neutral = float((spread <= 12).mean())  # black-on-white lettering, even after palette reduction
    white = float((px.min(axis=-1) >= 245).mean())
    dark = int((px.max(axis=-1) < TEXT_DARK).sum())
    return neutral, white, dark


def _caption_like(band) -> bool:
    """A render_proof caption band: neutral (black text on white, anti-aliased), mostly white,
    with one line of lettering that starts at the left margin (render_proof writes it at x=10)
    below a blank top row. Art, the checkerboard (half grey) and the magenta cut line fail this."""
    import numpy as np

    if band.size == 0:
        return False
    neutral, white, dark = _band_stats(band)
    if not (neutral >= 0.94 and white >= 0.8 and dark >= 12):
        return False
    ys, xs = np.nonzero(band.max(axis=-1) < TEXT_DARK)
    return bool(2 <= xs.min() <= 10 + len(band) // 2 and ys.min() >= 1)


def caption_band_height(img) -> int:
    """Rows of the size caption under a proof, or 0 when there is none.

    First the height render_proof uses (render.py: font size max(14, w // 28), band 2 x size;
    32 px with Pillow's bitmap font), confirmed by the band's content. Otherwise the trailing
    rows that look like a caption band (white, neutral, with lettering), at most a quarter of
    the image. Works on the pipeline's RGB proofs and on palette-reduced copies."""
    import numpy as np

    if img.mode in ("P", "L"):  # a palette-reduced copy (the demo folder slims its proofs)
        img = img.convert("RGBA")
    if img.mode == "RGBA":
        if img.getchannel("A").getextrema()[0] < 255:
            return 0  # transparent: a fixed.png, not a proof; it has no caption
        img = img.convert("RGB")
    if img.mode != "RGB":
        return 0
    arr = np.asarray(img)
    h, w = arr.shape[:2]
    for band_h in dict.fromkeys((int(max(14, w // 28) * 2), 32)):
        if 0 < band_h < h // 2 and _caption_like(arr[h - band_h:]):
            return band_h
    n = 0
    while n < h // 4:  # grow upward while each row stays white and neutral
        neutral, white, _ = _band_stats(arr[h - n - 1: h - n])
        if neutral < 0.97 or white < 0.8:
            break
        n += 1
    return n if n >= 12 and _caption_like(arr[h - n:]) else 0


def proof_without_caption(path: Path) -> bytes | None:
    """PNG bytes of the proof with its caption band cropped off, or None to serve the file as is."""
    from PIL import Image

    try:
        with Image.open(path) as im:
            im.load()
            band = caption_band_height(im)
            if not band:
                return None
            buf = io.BytesIO()
            im.crop((0, 0, im.width, im.height - band)).save(buf, "PNG")
            return buf.getvalue()
    except Exception:  # unreadable or exotic files are served unchanged
        return None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class LabelItem:
    image: str  # sha256 of the original image
    proof: str | None  # sha256 of the proof image (pass 2), None in pass 1
    path: Path  # the file shown: the original (pass 1) or the proof (pass 2)

    @property
    def shown(self) -> str:
        """Hash of the file on screen; it is also the URL id, so file names never leak."""
        return self.proof or self.image


def items_from_dir(directory: Path) -> list[LabelItem]:
    """Pass 1 items: every PNG/JPG/WebP directly in `directory` (or its images/ folder)."""
    directory = Path(directory)
    if (directory / "images").is_dir():
        directory = directory / "images"
    seen: dict[str, LabelItem] = {}
    for path in sorted(directory.iterdir()):
        if path.is_file() and path.suffix.lower() in IMAGE_EXTS:
            sha = sha256_file(path)
            seen.setdefault(sha, LabelItem(image=sha, proof=None, path=path))
    return list(seen.values())


def proof_items(pairs: Iterable[tuple[str, Path]]) -> list[LabelItem]:
    """Pass 2 items from (original image sha, proof path) pairs, de-duplicated by proof hash:
    a bit-identical proof produced by both modes is shown, and labelled, once."""
    seen: dict[str, LabelItem] = {}
    for image_sha, proof_path in pairs:
        proof_path = Path(proof_path)
        if not proof_path.is_file():
            continue
        sha = sha256_file(proof_path)
        seen.setdefault(sha, LabelItem(image=image_sha, proof=sha, path=proof_path))
    return list(seen.values())


def items_from_manifest(path: Path) -> list[LabelItem]:
    """Items from a JSON list of {"image": sha, "proof": sha|null, "path": file} (paths relative to it)."""
    path = Path(path)
    rows = json.loads(path.read_text(encoding="utf-8"))
    items = []
    for row in rows:
        file = Path(row["path"])
        if not file.is_absolute():
            file = path.parent / file
        items.append(LabelItem(image=row["image"], proof=row.get("proof"), path=file))
    return items


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class LabelError(ValueError):
    pass


class LabelSession:
    """One labelling pass over a fixed, shuffled list of items, persisted to labels.jsonl."""

    def __init__(self, items: list[LabelItem], labels_path: Path, pass_no: int, seed: int = DEFAULT_SEED,
                 caption: str = "3 in die-cut sticker", shuffle: bool = True):
        if pass_no not in PASS_LABELS:
            raise LabelError(f"pass must be 1 or 2, got {pass_no!r}")
        unique: dict[tuple[str, str | None], LabelItem] = {}
        for item in items:
            if pass_no == 2 and not item.proof:
                raise LabelError("pass 2 items need a proof hash")
            # pass 2 is keyed by the proof alone: a bit-identical proof is labelled once
            unique.setdefault((item.proof, None) if pass_no == 2 else (item.image, None), item)
        ordered = list(unique.values())
        if shuffle:
            ordered.sort(key=lambda it: it.shown)  # by content hash ...
            random.Random(seed).shuffle(ordered)  # ... then a fixed-seed shuffle
        self.items = ordered
        self.pass_no = pass_no
        self.labels_path = Path(labels_path)
        self.caption = caption if pass_no == 1 else None  # pass 2 shows the proof only
        self._by_shown = {it.shown: it for it in ordered}
        self._lock = threading.Lock()
        self._served: dict[str, tuple[bytes, str]] = {}

    @classmethod
    def from_label_file(cls, path: Path) -> "LabelSession":
        """A session from realset's label-pass{1,2}.json:
        {"pass", "caption", "keys", "labels": "labels.jsonl", "items": [{"image", "proof", "file"}]}.
        Items are already shuffled there, so their order is kept; files are relative to the JSON."""
        path = Path(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        pass_no = int(data["pass"])
        items = [LabelItem(image=it["image"], proof=it.get("proof"), path=path.parent / it["file"])
                 for it in data.get("items", [])]
        labels = path.parent / (data.get("labels") or "labels.jsonl")
        return cls(items, labels, pass_no, caption=data.get("caption") or "3 in die-cut sticker", shuffle=False)

    # -------------------------------------------------------------- reading

    def item_for(self, sha: str) -> LabelItem | None:
        return self._by_shown.get(sha)

    def image_bytes(self, item: LabelItem) -> tuple[bytes, str]:
        """What the page shows for an item: pass 1 the original file; pass 2 the proof picture
        with render_proof's size caption cropped off (cached; the file itself is untouched)."""
        ctype = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}.get(item.path.suffix.lower(), "image/png")
        if self.pass_no != 2:
            return item.path.read_bytes(), ctype
        with self._lock:
            hit = self._served.get(item.shown)
        if hit is None:
            cropped = proof_without_caption(item.path)
            hit = (cropped, "image/png") if cropped is not None else (item.path.read_bytes(), ctype)
            with self._lock:
                if len(self._served) > 64:
                    self._served.clear()
                self._served[item.shown] = hit
        return hit

    def current_labels(self) -> dict[tuple[str | None, str | None], str]:
        """Last label per (image, proof) key for this pass; malformed lines are ignored."""
        out: dict[tuple[str | None, str | None], str] = {}
        if not self.labels_path.exists():
            return out
        for line in self.labels_path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("pass") == self.pass_no and row.get("label") in PASS_LABELS[self.pass_no]:
                key = (None, row.get("proof")) if self.pass_no == 2 else (row.get("image"), None)
                out[key] = row["label"]
        return out

    def _key(self, item: LabelItem) -> tuple[str | None, str | None]:
        """Pass 1 is keyed by the image; pass 2 by the proof alone (as realset eval reads it)."""
        return (None, item.proof) if self.pass_no == 2 else (item.image, None)

    def view(self, url_prefix: str = "/api/label/image/") -> dict:
        labels = self.current_labels()
        rows = []
        for i, item in enumerate(self.items):
            rows.append({"index": i, "sha": item.shown, "url": url_prefix + item.shown,
                         "label": labels.get(self._key(item))})
        done = sum(1 for r in rows if r["label"])
        start = next((r["index"] for r in rows if not r["label"]), len(rows))
        return {"pass": self.pass_no, "caption": self.caption, "keys": PASS_KEYS[self.pass_no],
                "total": len(rows), "done": done, "start": start, "items": rows,
                "labels_file": str(self.labels_path)}

    # -------------------------------------------------------------- writing

    def record(self, index: int, label: str) -> dict:
        """Append one label row (flushed and fsynced before returning)."""
        if not isinstance(index, int) or not 0 <= index < len(self.items):
            raise LabelError(f"no item at index {index!r}")
        if label not in PASS_LABELS[self.pass_no]:
            raise LabelError(f"label must be one of {PASS_LABELS[self.pass_no]} in pass {self.pass_no}")
        item = self.items[index]
        row = {"ts": utc_now(), "pass": self.pass_no, "image": item.image,
               "proof": item.proof if self.pass_no == 2 else None, "label": label}
        with self._lock:
            self.labels_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.labels_path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(row) + "\n")
                fh.flush()
                os.fsync(fh.fileno())
        return row
