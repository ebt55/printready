"""Where things live. Everything the server writes goes under the working root (the repo when run
with `uv run`): runs in out/workbench/, caches in out/.cache/. Bundled samples and the demo folder
live in examples/samples/ of the source tree."""

from __future__ import annotations

from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
STATIC_DIR = WEB_DIR / "static"
_REPO_GUESS = WEB_DIR.parents[2]  # src/printready/web -> repo root


def repo_root() -> Path:
    """The source checkout if we are running from one, else the current directory."""
    if (_REPO_GUESS / "pyproject.toml").exists():
        return _REPO_GUESS
    return Path.cwd()


def samples_dir() -> Path:
    for base in (repo_root(), Path.cwd()):
        candidate = base / "examples" / "samples"
        if candidate.exists():
            return candidate
    return repo_root() / "examples" / "samples"


def demo_dir() -> Path:
    """Saved demo runs (RunResult JSON + files + events), rebuilt by `printready serve --rebuild-demo`."""
    return samples_dir() / "demo"


def default_out_dir(root: Path) -> Path:
    return root / "out" / "workbench"


def cache_dir(root: Path) -> Path:
    return root / "out" / ".cache"


def ledger_path(root: Path) -> Path:
    return root / "results" / "spend-ledger.jsonl"


def safe_child(base: Path, relative: str) -> Path | None:
    """Resolve `relative` under `base`, or None if it escapes `base` (path traversal guard)."""
    if not relative or "\x00" in relative:
        return None
    base = base.resolve()
    try:
        target = (base / relative).resolve()
    except (OSError, ValueError):
        return None
    if target == base or base not in target.parents:
        return None
    return target
