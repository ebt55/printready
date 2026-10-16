"""Workbench runs under out/workbench/<run-id>/ and the RunView the UI renders.

A run directory holds:
    run.json           our record: id, created, filename, spec, mode, model, status, outcome, timings
    original.<ext>     the uploaded or sample image (the path handed to run_rules / run_agent)
    events.jsonl       every on_event event, in order (the SSE stream replays it)
    ...                whatever the pipeline wrote: report.json, fixed.png, proof.png, cutline.svg, ...
    _thumb.png         a small thumbnail for the recent-runs list (ours; names starting "_" are private)

Only directories with a run.json are runs, so the run list never picks up anything else.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from PIL import Image

EVENT_TYPES = ("step", "turn", "findings", "done", "error")
PRIMARY_DOWNLOADS = ("fixed.png", "cutline.svg", "proof.png", "report.json")
EXTRA_DOWNLOADS = ("customer_message.md", "report.html", "overlay.png", "log.jsonl")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def jsonable(value: Any) -> Any:
    """Turn contract objects (anything with to_dict), dataclasses, numpy values and paths into JSON."""
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return jsonable(value.to_dict())
    if is_dataclass(value) and not isinstance(value, type):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item") and callable(value.item) and not isinstance(value, (str, bytes)):
        try:
            return value.item()  # numpy scalar
        except (TypeError, ValueError):
            pass
    if hasattr(value, "tolist"):
        return value.tolist()
    return value


# ------------------------------------------------------------------ image sizes (cached)

_size_cache: dict[tuple[str, float], tuple[int, int]] = {}


def image_size(path: Path) -> tuple[int, int] | None:
    try:
        key = (str(path), path.stat().st_mtime)
    except OSError:
        return None
    if key not in _size_cache:
        try:
            with Image.open(path) as im:  # reads the header only
                _size_cache[key] = im.size
        except Exception:
            return None
    return _size_cache[key]


def make_thumb(src: Path, dest: Path, max_px: int = 160) -> bool:
    try:
        with Image.open(src) as im:
            im = im.convert("RGBA")
            im.thumbnail((max_px, max_px), Image.LANCZOS)
            dest.parent.mkdir(parents=True, exist_ok=True)
            im.save(dest, optimize=True)
        return True
    except Exception:
        return False


# ------------------------------------------------------------------ the RunView

def _basename_of_output(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value).name


def build_view(run_dir: Path, record: dict, url: Callable[[str], str], events: list[dict],
               original: tuple[Path, str] | None = None, readonly: bool = False) -> dict:
    """The one JSON shape the Workbench renders for a run (live, saved real-set item, or export).

    `url(name)` maps a file name in `run_dir` to the URL it is served at. `original` overrides
    where the original image lives (saved real-set items keep it outside the run directory).
    """
    files = {}
    if run_dir.exists():
        files = {f.name: f.stat().st_size for f in run_dir.iterdir() if f.is_file() and not f.name.startswith("_")}

    def img(name: str | None) -> dict | None:
        if not name or name not in files:
            return None
        size = image_size(run_dir / name)
        return {"url": url(name), "name": name, "w": size[0] if size else None, "h": size[1] if size else None}

    result = None
    if record.get("status") == "done":
        done = next((e for e in reversed(events) if e.get("type") == "done"), None)
        result = done.get("result") if done else None
        if result is None and "report.json" in files:
            try:
                result = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                result = None

    if original is not None:
        opath, ourl = original
        size = image_size(opath)
        original_img = {"url": ourl, "name": opath.name, "w": size[0] if size else None, "h": size[1] if size else None}
    else:
        original_img = img(record.get("original"))

    # Prefer the file names the pipeline reported in RunResult.outputs, fall back to the defaults.
    outputs = {k: _basename_of_output(v) for k, v in ((result or {}).get("outputs") or {}).items()}
    fixed_name = outputs.get("fixed") or "fixed.png"
    proof_name = outputs.get("proof") or "proof.png"
    cut_name = outputs.get("cutline") or "cutline.svg"

    steps = []
    for e in events:
        if e.get("type") == "step":
            steps.append({"step": e.get("step") or {}, "preview": img(e.get("preview"))})
    if not steps and result:  # a saved run without its event log: history + previews from outputs
        history = result.get("history") or (result.get("art") or {}).get("history", [])
        steps = [{"step": s, "preview": img(outputs.get(f"step-{i + 1}"))} for i, s in enumerate(history)]
    turns = []
    for e in events:
        if e.get("type") == "turn":
            t = {k: v for k, v in e.items() if k not in ("type", "image_url")}
            t["image"] = img(e.get("image")) if e.get("image") else None
            turns.append(t)
    reports = [e["report"] for e in events if e.get("type") == "findings" and isinstance(e.get("report"), dict)]
    error = record.get("error")
    if not error:
        err = next((e for e in events if e.get("type") == "error"), None)
        error = err.get("message") if err else None

    downloads = []
    for name in PRIMARY_DOWNLOADS + EXTRA_DOWNLOADS:
        if name in files:
            downloads.append({"name": name, "url": url(name), "bytes": files[name], "primary": name in PRIMARY_DOWNLOADS})

    return {
        "id": record.get("id"),
        "created": record.get("created"),
        "filename": record.get("filename"),
        "sample_id": record.get("sample_id"),
        "spec": record.get("spec") or {"product": "die_cut", "size_in": 3.0},
        "mode": record.get("mode"),
        "model": record.get("model"),
        "vision": bool(record.get("vision")),
        "demo": bool(record.get("demo")),
        "engine": record.get("engine"),
        "readonly": readonly,
        "status": record.get("status", "done"),
        "error": error,
        "duration_ms": record.get("duration_ms"),
        "event_count": len(events),
        "images": {"original": original_img, "fixed": img(fixed_name), "proof": img(proof_name),
                   "overlay": img(outputs.get("overlay") or "overlay.png")},
        "cutline": {"url": url(cut_name), "name": cut_name} if cut_name in files else None,
        "steps": steps,
        "turns": turns,
        "reports": {"first": reports[0] if reports else None, "latest": reports[-1] if reports else None},
        "result": result,
        "downloads": downloads,
        "notices": record.get("notices", []),
    }


# ------------------------------------------------------------------ live runs

class RunJob:
    """One run: its record, its ordered event log, and a condition SSE readers wait on."""

    def __init__(self, run_dir: Path, record: dict, events: list[dict] | None = None):
        self.dir = run_dir
        self.record = record
        self.events: list[dict] = events or []
        self.cond = threading.Condition()
        self.finished = record.get("status") in ("done", "error")
        self._t0 = time.monotonic()

    # convenient accessors for runners
    @property
    def id(self) -> str:
        return self.record["id"]

    @property
    def mode(self) -> str:
        return self.record["mode"]

    @property
    def size_in(self) -> float:
        return float(self.record["spec"]["size_in"])

    @property
    def model(self) -> str | None:
        return self.record.get("model")

    @property
    def vision(self) -> bool:
        return bool(self.record.get("vision"))

    @property
    def sample_id(self) -> str | None:
        return self.record.get("sample_id")

    @property
    def input_path(self) -> Path:
        return self.dir / self.record["original"]

    def save_record(self) -> None:
        tmp = self.dir / "run.json.tmp"
        tmp.write_text(json.dumps(self.record, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.dir / "run.json")

    def mark_running(self) -> None:
        self.record["status"] = "running"
        self.record["started"] = utc_now()
        self._t0 = time.monotonic()
        self.save_record()

    def emit(self, event: Any) -> None:
        """The on_event callback handed to run_rules / run_agent. Thread-safe; late events are ignored."""
        ev = jsonable(event)
        if not isinstance(ev, dict) or ev.get("type") not in EVENT_TYPES:
            return
        with self.cond:
            if self.finished:
                return
            self.events.append(ev)
            with open(self.dir / "events.jsonl", "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(ev) + "\n")
            if ev["type"] == "done":
                self._finalize(ev.get("result"))
            elif ev["type"] == "error":
                self.record["status"] = "error"
                self.record["error"] = str(ev.get("message") or "the run failed")
                self._close()
            self.cond.notify_all()

    def finish(self, result: Any = None) -> None:
        """Called after the runner returns: emits `done` with the returned RunResult if the runner did not."""
        if self.finished:
            return
        if result is None:
            self.emit({"type": "error", "message": "the runner returned without a result"})
        else:
            self.emit({"type": "done", "result": jsonable(result)})

    def fail(self, message: str) -> None:
        self.emit({"type": "error", "message": message})

    def _close(self) -> None:
        self.finished = True
        self.record["finished"] = utc_now()
        self.record["duration_ms"] = int((time.monotonic() - self._t0) * 1000)
        self.save_record()

    def _finalize(self, result: dict | None) -> None:
        result = result or {}
        if not (self.dir / "report.json").exists() and result:
            (self.dir / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        self.record["status"] = "done"
        self.record["outcome"] = result.get("outcome")
        self.record["cost_usd"] = result.get("cost_usd", 0.0)
        src = self.dir / "fixed.png"
        make_thumb(src if src.exists() else self.input_path, self.dir / "_thumb.png")
        self._close()

    def events_since(self, start: int, timeout: float) -> tuple[list[dict], bool]:
        with self.cond:
            if len(self.events) <= start and not self.finished:
                self.cond.wait(timeout)
            return list(self.events[start:]), self.finished


class RunStore:
    """All workbench runs. Reads and writes only `out_dir` (default out/workbench/)."""

    def __init__(self, out_dir: Path, url_prefix: str = "/api/runs/"):
        self.out_dir = Path(out_dir)
        self.url_prefix = url_prefix
        self._jobs: dict[str, RunJob] = {}
        self._lock = threading.Lock()

    def file_url(self, run_id: str, name: str) -> str:
        return f"{self.url_prefix}{run_id}/files/{name}"

    def create(self, *, filename: str, data: bytes, ext: str, size_in: float, mode: str, model: str | None,
               vision: bool, sample_id: str | None, demo: bool, engine: str, notices: list[str] | None = None) -> RunJob:
        run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3)
        run_dir = self.out_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        original = f"original{ext}"
        (run_dir / original).write_bytes(data)
        record = {"id": run_id, "created": utc_now(), "filename": filename, "original": original,
                  "spec": {"product": "die_cut", "size_in": size_in, "prompt": None}, "mode": mode,
                  "model": model, "vision": vision, "sample_id": sample_id, "demo": demo, "engine": engine,
                  "status": "queued", "outcome": None, "notices": notices or []}
        job = RunJob(run_dir, record)
        job.save_record()
        with self._lock:
            self._jobs[run_id] = job
        return job

    def _valid_id(self, run_id: str) -> bool:
        return bool(run_id) and all(c.isalnum() or c == "-" for c in run_id) and len(run_id) < 64

    def get(self, run_id: str) -> RunJob | None:
        if not self._valid_id(run_id):
            return None
        with self._lock:
            job = self._jobs.get(run_id)
            if job:
                return job
            run_dir = self.out_dir / run_id
            try:
                record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            events = []
            ev_path = run_dir / "events.jsonl"
            if ev_path.exists():
                for line in ev_path.read_text(encoding="utf-8").splitlines():
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
            if record.get("status") in ("queued", "running"):
                # A run that was in flight when the server stopped: it will never finish.
                record["status"] = "error"
                record["error"] = "the server stopped before this run finished"
            job = RunJob(run_dir, record, events)
            job.finished = True
            self._jobs[run_id] = job
            return job

    def view(self, run_id: str) -> dict | None:
        job = self.get(run_id)
        if job is None:
            return None
        with job.cond:
            events = list(job.events)
            record = dict(job.record)
        return build_view(job.dir, record, lambda name: self.file_url(run_id, name), events)

    def list(self, limit: int = 60) -> list[dict]:
        if not self.out_dir.exists():
            return []
        out = []
        dirs = sorted((d for d in self.out_dir.iterdir() if (d / "run.json").is_file()), reverse=True)
        for d in dirs[:limit]:
            live = self._jobs.get(d.name)
            try:
                record = dict(live.record) if live else json.loads((d / "run.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            thumb = d / "_thumb.png"
            out.append({"id": record.get("id", d.name), "created": record.get("created"),
                        "filename": record.get("filename"), "mode": record.get("mode"),
                        "model": record.get("model"), "size_in": (record.get("spec") or {}).get("size_in"),
                        "status": record.get("status"), "outcome": record.get("outcome"),
                        "demo": record.get("demo", False),
                        "thumb": f"{self.url_prefix}{d.name}/thumb" if thumb.exists() else
                        self.file_url(d.name, record.get("original", ""))})
        return out

    def file_path(self, run_id: str, name: str) -> Path | None:
        from printready.web.paths import safe_child

        job = self.get(run_id)
        if job is None:
            return None
        if name == "thumb":
            p = job.dir / "_thumb.png"
            return p if p.exists() else None
        p = safe_child(job.dir, name)
        if p is None or not p.is_file() or p.parent != job.dir.resolve() or p.name in ("run.json.tmp",):
            return None
        return p
