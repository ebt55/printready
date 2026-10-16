"""Real image set: Grok image outputs from our prompts, run through both modes, labelled by Ebin.

Layout for a split ("dev": 10 prompts, tuning only; "test": 50 prompts, frozen by PREREG.md):
    realset/prompts-dev.txt | realset/prompts.txt        prompts, one per line (committed)
    data/realset/<split>/manifest.jsonl                  one line per generated image (committed)
    data/realset/<split>/images/<sha256>.<ext>           the images, named by content (gitignored)
    data/realset/<split>/labels.jsonl                    Ebin's keypress labels (committed)
    data/realset/<split>/label-pass{1,2}.json            what the label page shows, by hash only
    data/realset/<split>/label-images/<sha256>.png       PNG copies the label page shows (gitignored)
    results/realset/<split>/<mode>/<sha256>/             per-image outputs of rules / agent mode
    results/realset/<split>/<mode>/runs.jsonl            one summary line per image run
File names never reveal which image model made an image.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from printready.spend import repo_root
from printready.types import Spec

SPLITS = ("dev", "test")
MODES = ("rules", "agent")
PROMPT_FILES = {"dev": "realset/prompts-dev.txt", "test": "realset/prompts.txt"}
ID_PREFIX = {"dev": "d", "test": "p"}
IMAGE_MODELS = ("xai:grok-imagine-image", "xai:grok-imagine-image-2.0")
ORDER_SIZE_IN = 3.0  # every real-set image is judged as a 3 in die-cut order
SEED = 7
SAMPLE_N = 50  # images Ebin labels
ROOT_ENV = "PRINTREADY_REALSET_ROOT"


@dataclass(frozen=True)
class Paths:
    split: str
    root: Path

    @classmethod
    def for_split(cls, split: str, root: Path | None = None) -> Paths:
        if split not in SPLITS:
            raise ValueError(f"split must be one of {SPLITS}, got {split!r}")
        root = root or os.environ.get(ROOT_ENV) or repo_root()  # the env var lets tests use a temp tree
        return cls(split, Path(root))

    @property
    def prompts(self) -> Path:
        return self.root / PROMPT_FILES[self.split]

    @property
    def data(self) -> Path:
        return self.root / "data" / "realset" / self.split

    @property
    def manifest(self) -> Path:
        return self.data / "manifest.jsonl"

    @property
    def labels(self) -> Path:
        return self.data / "labels.jsonl"

    @property
    def results(self) -> Path:
        return self.root / "results" / "realset" / self.split

    def runs(self, mode: str) -> Path:
        return self.results / mode / "runs.jsonl"


def spec_for(prompt: str | None) -> Spec:
    return Spec("die_cut", ORDER_SIZE_IN, prompt=prompt)


def load_prompts(path: Path, prefix: str) -> list[tuple[str, str]]:
    """(id, prompt) pairs; ids are prefix + 2-digit line order, comments and blanks skipped."""
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()]
    prompts = [ln for ln in lines if ln and not ln.startswith("#")]
    return [(f"{prefix}{i:02d}", p) for i, p in enumerate(prompts, start=1)]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def last_by(rows: Iterable[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    """The last row per value of `key` (append-only files: the last line wins)."""
    return {row[key]: row for row in rows}


def sample_shas(manifest: list[dict[str, Any]], n: int = SAMPLE_N, seed: int = SEED) -> list[str]:
    """The seeded labelling sample: n image hashes drawn from the sorted hashes (model-blind)."""
    shas = sorted({e["sha256"] for e in manifest})
    return sorted(random.Random(seed).sample(shas, min(n, len(shas))))


def shuffled(items: list[Any], seed: int = SEED) -> list[Any]:
    out = list(items)
    random.Random(seed).shuffle(out)
    return out


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
