"""The JSON API. One method per endpoint; server.py only does HTTP plumbing.

Routes (04-WORKBENCH.md "Backend API"):
    GET  /api/state                                    profile, models, prices, spend, samples
    GET  /api/samples/<id>/image[?thumb=1]             bundled sample image
    POST /api/runs                                     {image_b64 | sample_id, filename, size_in, mode, model, vision}
    GET  /api/runs                                     recent runs (out/workbench/ only)
    GET  /api/runs/<id>                                RunView
    GET  /api/runs/<id>/events[?from=N]                SSE: step, turn, findings, done, error
    GET  /api/runs/<id>/files/<name>                   any output file of the run
    GET  /api/results/bench/<split>                    benchmark metrics
    GET  /api/results/realset[/<run>]                  real-set runs / one run's gallery + agreement
    GET  /api/results/realset/<run>/items/<sha>/<mode> a saved item as a read-only RunView
    GET  /api/label/session[?pass=N] | /api/label/image/<sha> | POST /api/label {index, label}

In label mode only "/", static files and /api/label/* exist; every other route is a 404.
"""

from __future__ import annotations

import base64
import binascii
import json
import mimetypes
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator

from printready.web import demo as demomod
from printready.web import results as res
from printready.web import state as webstate
from printready.web.label import LabelError, LabelSession, items_from_dir
from printready.web.paths import STATIC_DIR, cache_dir, safe_child
from printready.web.runner import DemoRunner, LiveRunner, live_status
from printready.web.runs import RunStore, image_size, make_thumb, read_agent_log

MAX_UPLOAD_BYTES = 20_000_000  # 20 MB, decimal, like the profile's max_upload_mb
MAX_BODY_BYTES = 28_000_000  # base64 of 20 MB plus JSON overhead
SIZE_MIN_IN, SIZE_MAX_IN = 0.5, 20.0
SIZES = [2, 3, 4, 5]
LABELLER = "Ebin"

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json", ".jsonl": "application/x-ndjson; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".md": "text/markdown; charset=utf-8", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8",
}


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "application/json"
    headers: dict[str, str] = field(default_factory=dict)
    stream: Callable[[Callable[[bytes], None]], None] | None = None  # SSE: writes until the run ends


def json_response(data: Any, status: int = 200) -> Response:
    return Response(status, json.dumps(data).encode("utf-8"))


def error(status: int, code: str, message: str) -> Response:
    return json_response({"error": code, "message": message}, status)


def file_response(path: Path, download_name: str | None = None) -> Response:
    ctype = CONTENT_TYPES.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"Cache-Control": "no-cache"}
    if download_name:
        headers["Content-Disposition"] = f'attachment; filename="{download_name}"'
    return Response(200, path.read_bytes(), ctype, headers)


def sniff_ext(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def clean_filename(name: Any, fallback: str) -> str:
    if not isinstance(name, str) or not name.strip():
        return fallback
    name = Path(name.replace("\\", "/")).name
    name = "".join(ch for ch in name if ch.isprintable())[:120].strip()
    return name or fallback


class App:
    def __init__(self, *, root: Path, out_dir: Path, demo: bool = False, demo_speed: float = 1.0,
                 label: LabelSession | None = None, demo_dir: Path | None = None, samples_dir: Path | None = None,
                 show_test: bool = False):
        from printready.web.paths import demo_dir as _demo_dir
        from printready.web.paths import samples_dir as _samples_dir

        self.root = Path(root)
        self.demo = demo
        self.show_test = show_test  # blinding: the test split is hidden unless asked for
        self.label = label
        self.label_mode = label is not None
        self.demo_dir = Path(demo_dir) if demo_dir else _demo_dir()
        self.samples_dir = Path(samples_dir) if samples_dir else _samples_dir()
        self.store = RunStore(out_dir)
        self.runner = DemoRunner(demo_speed, self.demo_dir, self.samples_dir) if demo else LiveRunner()
        self.pool = ThreadPoolExecutor(max_workers=4 if demo else 1, thread_name_prefix="printready-run")
        self._demo_labels: dict[int, LabelSession] = {}
        self._lock = threading.Lock()
        self.routes: list[tuple[str, re.Pattern, Callable[..., Response], bool]] = []
        r = self._route
        r("GET", r"/", self.index, label_ok=True)
        r("GET", r"/index\.html", self.index, label_ok=True)
        r("GET", r"/static/(?P<path>.+)", self.static, label_ok=True)
        r("GET", r"/favicon\.ico", self.favicon, label_ok=True)
        r("GET", r"/api/state", self.state)
        r("GET", r"/api/samples/(?P<sid>[\w-]+)/image", self.sample_image)
        r("GET", r"/api/runs", self.list_runs)
        r("POST", r"/api/runs", self.create_run)
        r("GET", r"/api/runs/(?P<rid>[\w-]+)", self.get_run)
        r("GET", r"/api/runs/(?P<rid>[\w-]+)/events", self.run_events)
        r("GET", r"/api/runs/(?P<rid>[\w-]+)/thumb", self.run_thumb)
        r("GET", r"/api/runs/(?P<rid>[\w-]+)/files/(?P<name>[^/]+)", self.run_file)
        r("GET", r"/api/results/bench/(?P<split>\w+)", self.bench)
        r("GET", r"/api/results/realset", self.realsets)
        r("GET", r"/api/results/realset/(?P<run>[\w.-]+)", self.realset)
        r("GET", r"/api/results/realset/(?P<run>[\w.-]+)/items/(?P<sha>[0-9a-f]{8,64})/(?P<mode>rules|agent)",
          self.realset_item)
        r("GET", r"/api/results/realset/(?P<run>[\w.-]+)/files/(?P<rel>.+)", self.realset_file)
        r("GET", r"/api/results/realset/(?P<run>[\w.-]+)/thumb/(?P<rel>.+)", self.realset_thumb)
        r("GET", r"/api/label/session", self.label_session, label_ok=True)
        r("GET", r"/api/label/image/(?P<sha>[0-9a-f]{64})", self.label_image, label_ok=True)
        r("POST", r"/api/label", self.label_post, label_ok=True)

    def _route(self, method: str, pattern: str, fn: Callable[..., Response], label_ok: bool = False) -> None:
        self.routes.append((method, re.compile(pattern + r"\Z"), fn, label_ok))

    # ------------------------------------------------------------------ dispatch

    def handle(self, method: str, path: str, query: dict[str, list[str]], body: Any) -> Response:
        allowed_methods = set()
        for m, pattern, fn, label_ok in self.routes:
            match = pattern.match(path)
            if not match:
                continue
            if self.label_mode and not label_ok:
                break  # label mode: the route does not exist
            if m != method:
                allowed_methods.add(m)
                continue
            kwargs = match.groupdict()
            if method == "POST":
                kwargs["body"] = body
            if fn in (self.run_events, self.label_session, self.sample_image, self.bench):
                kwargs["query"] = query
            return fn(**kwargs)
        if allowed_methods:
            return error(405, "method_not_allowed", f"use {', '.join(sorted(allowed_methods))}")
        if self.label_mode:
            return error(404, "not_found", "not available in label mode")
        return error(404, "not_found", f"no route for {path}")

    # ------------------------------------------------------------------ shell and static files

    def index(self) -> Response:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        mode = "label" if self.label_mode else "app"
        html = re.sub(r'<meta name="printready-mode" content="\w+"\s*/?>',
                      f'<meta name="printready-mode" content="{mode}">', html, count=1)
        return Response(200, html.encode("utf-8"), CONTENT_TYPES[".html"], {"Cache-Control": "no-cache"})

    def static(self, path: str) -> Response:
        p = safe_child(STATIC_DIR, path)
        if p is None or not p.is_file():
            return error(404, "not_found", "no such static file")
        return file_response(p)

    def favicon(self) -> Response:
        p = STATIC_DIR / "favicon.svg"
        return Response(200, p.read_bytes(), CONTENT_TYPES[".svg"]) if p.exists() else Response(204)

    # ------------------------------------------------------------------ state

    def samples(self) -> list[dict]:
        out = []
        for s in demomod.load_samples(self.samples_dir, self.demo_dir, include_real=self.demo):
            out.append({"id": s["id"], "title": s["title"], "blurb": s["blurb"], "size_in": s["size_in"],
                        "width": s.get("width"), "height": s.get("height"), "group": s.get("group", "procedural"),
                        "note": s.get("note"), "prompt": s.get("prompt"), "image_model": s.get("image_model"),
                        "has_text": bool((s.get("vision") or {}).get("text")),
                        "image": f"/api/samples/{s['id']}/image", "thumb": f"/api/samples/{s['id']}/image?thumb=1"})
        return out

    def sources(self) -> list[res.Source]:
        """Where Results reads from: the repo first; in --demo also the demo folder (same layout)."""
        out = [res.Source(self.root, show_blind=self.show_test)]
        if self.demo:
            out.append(res.Source(self.demo_dir, demo=True))
        return out

    def state(self) -> Response:
        status = live_status()
        idx = demomod.load_index(self.demo_dir) if self.demo else {}
        sources = self.sources()
        return json_response({
            "version": webstate.version(),
            "mode": "label" if self.label_mode else "app",
            "demo": self.demo,
            "demo_engine": idx.get("engine") if self.demo else None,
            "static": False,
            "profile": webstate.profile_payload(),
            "models": webstate.models_payload(),
            "default_model": webstate.MODELS[0]["id"],
            "spend": webstate.spend_payload(self.root),
            "sizes": SIZES,
            "size_limits": {"min": SIZE_MIN_IN, "max": SIZE_MAX_IN},
            "products": [{"id": "die_cut", "label": "Die-cut sticker"}],
            "max_upload_mb": MAX_UPLOAD_BYTES / 1_000_000,
            "runner": {"engine": "demo" if self.demo else "live", "rules": status["rules"], "agent": status["agent"]},
            "samples": self.samples(),
            "results": {"bench_splits": res.bench_splits(sources), "realset_runs": res.realset_runs(sources)},
            "labeller": LABELLER,
            "label": {"available": self.demo, "demo": self.demo},
        })

    def sample_image(self, sid: str, query: dict) -> Response:
        sample = next((s for s in demomod.load_samples(self.samples_dir, self.demo_dir, include_real=self.demo)
                       if s["id"] == sid), None)
        if not sample:
            return error(404, "not_found", f"no sample {sid!r}")
        src = demomod.sample_path(sample, self.samples_dir, self.demo_dir)
        if query.get("thumb"):
            dest = cache_dir(self.root) / "thumbs" / f"sample-{sid}-{int(src.stat().st_mtime)}.png"
            if dest.exists() or make_thumb(src, dest, 200):
                return file_response(dest)
        return file_response(src)

    # ------------------------------------------------------------------ runs

    def list_runs(self) -> Response:
        return json_response({"runs": self.store.list()})

    def create_run(self, body: Any) -> Response:
        if not isinstance(body, dict):
            return error(400, "bad_request", "send a JSON object")
        mode = body.get("mode", "rules")
        if mode not in ("rules", "agent"):
            return error(400, "bad_mode", "mode must be rules or agent")
        try:
            size_in = float(body.get("size_in", 3))
        except (TypeError, ValueError):
            return error(400, "bad_size", "size_in must be a number of inches")
        if not SIZE_MIN_IN <= size_in <= SIZE_MAX_IN:
            return error(400, "bad_size", f"size must be between {SIZE_MIN_IN:g} and {SIZE_MAX_IN:g} in")
        vision = True if mode == "agent" else bool(body.get("vision"))
        model = body.get("model") or webstate.MODELS[0]["id"]
        if model not in {m["id"] for m in webstate.MODELS}:
            return error(400, "bad_model", f"unknown model {model!r}")
        if mode == "rules" and not vision:
            model = None

        sample_id = body.get("sample_id")
        sample = None
        if sample_id:
            sample = next((s for s in demomod.load_samples(self.samples_dir, self.demo_dir, include_real=self.demo)
                           if s["id"] == sample_id), None)
            if not sample:
                return error(404, "no_sample", f"no sample {sample_id!r}")
            data = demomod.sample_path(sample, self.samples_dir, self.demo_dir).read_bytes()
            filename = sample["title"] if sample.get("group") == "real" else sample["file"]
        else:
            raw = body.get("image_b64")
            if not isinstance(raw, str) or not raw:
                return error(400, "no_image", "send image_b64 or sample_id")
            if raw.startswith("data:"):
                raw = raw.split(",", 1)[-1]
            if len(raw) > MAX_BODY_BYTES:
                return error(413, "too_large", "the image is over the 20 MB upload limit")
            try:
                data = base64.b64decode(raw, validate=True)
            except (binascii.Error, ValueError):
                return error(400, "bad_base64", "image_b64 is not valid base64")
            if len(data) > MAX_UPLOAD_BYTES:
                return error(413, "too_large", f"the image is {len(data) / 1e6:.1f} MB; the limit is 20 MB")
            filename = clean_filename(body.get("filename"), "upload")
        ext = sniff_ext(data)
        if ext is None:
            return error(415, "bad_type", "only PNG, JPG and WebP images are supported")

        notices = []
        canned = real = False
        if self.demo:
            canned = sample_id and demomod.canned_run_dir(sample_id, mode, size_in, vision, self.demo_dir)
            real = sample_id and (sample or {}).get("group") == "real"
            if canned and real and mode == "agent":
                notices.append("Real Grok output, dev set: the image and every model turn are the saved live run "
                               "(grok-4.3). Replayed with long waits shortened; each turn shows its real latency. "
                               "Nothing is charged now.")
            elif canned and real:
                notices.append("Real Grok output, dev set: the image and the text check's answer are the saved live "
                               "run (grok-4.3), replayed. Nothing is charged now.")
            elif canned:
                notices.append("Demo: replayed from a saved run. Nothing is charged.")
            else:
                notices.append("Demo: the real checks and fixes, with a scripted model standing in for Grok. "
                               "Nothing is charged.")
                if vision and not sample_id:
                    notices.append("Demo: the scripted model cannot read an uploaded image, so the text check "
                                   "reports no lettering.")
        else:
            status = live_status()[mode]
            if not status["ready"]:
                return error(503, "not_ready", f"{mode} mode is not wired yet: {status['reason']}. "
                                               "Start with --demo to explore with simulated runs.")
            est = webstate.estimate_usd(mode, model, vision)
            if est > 0:
                spend = webstate.spend_payload(self.root)
                if spend["total_usd"] + est > spend["cap_usd"]:
                    return error(402, "budget", f"this run could cost up to ${est:.2f}; the ledger is at "
                                                f"${spend['total_usd']:.2f} of the ${spend['cap_usd']:.2f} cap")

        job = self.store.create(filename=filename, data=data, ext=ext, size_in=size_in, mode=mode, model=model,
                                vision=vision, sample_id=sample_id, demo=self.demo, engine=self.runner.engine,
                                notices=notices, real=bool(self.demo and canned and real))
        self.pool.submit(self.runner.run, job)
        return json_response({"run_id": job.id}, 201)

    def get_run(self, rid: str) -> Response:
        view = self.store.view(rid)
        return json_response(view) if view else error(404, "not_found", f"no run {rid!r}")

    def run_file(self, rid: str, name: str) -> Response:
        p = self.store.file_path(rid, name)
        if p is None:
            return error(404, "not_found", "no such file in this run")
        return file_response(p)

    def run_thumb(self, rid: str) -> Response:
        p = self.store.file_path(rid, "thumb")
        return file_response(p) if p else error(404, "not_found", "no thumbnail yet")

    def run_events(self, rid: str, query: dict) -> Response:
        job = self.store.get(rid)
        if job is None:
            return error(404, "not_found", f"no run {rid!r}")
        try:
            start = max(0, int((query.get("from") or ["0"])[0]))
        except ValueError:
            start = 0

        def stream(write: Callable[[bytes], None]) -> None:
            write(b"retry: 2000\n\n")
            i = start
            while True:
                events, finished = job.events_since(i, timeout=15.0)
                for ev in events:
                    ev = self._enrich(job, ev)
                    write(f"id: {i}\nevent: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode("utf-8"))
                    i += 1
                if not events and not finished:
                    write(b": keepalive\n\n")
                if finished and i >= len(job.events):
                    write(b"event: end\ndata: {}\n\n")
                    return

        return Response(200, content_type="text/event-stream", stream=stream,
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def _image_info(self, job, name: str) -> dict | None:
        path = job.dir / name
        if not name or not path.is_file():
            return None
        size = image_size(path)
        return {"url": self.store.file_url(job.id, name), "name": name,
                "w": size[0] if size else None, "h": size[1] if size else None}

    def _enrich(self, job, ev: dict) -> dict:
        """Add served URLs (and pixel sizes) for the files an event names, so the page never
        builds file URLs itself: step -> preview_info, turn -> image_info."""
        if ev.get("type") == "step" and isinstance(ev.get("preview"), str):
            return {**ev, "preview_info": self._image_info(job, ev["preview"])}
        if ev.get("type") == "turn":
            # the log is written before each turn is emitted: inner model calls and the context are there
            log = read_agent_log(job.dir)
            out = {**ev, "sub_calls": log["sub_calls"].get(ev.get("n"), [])}
            if isinstance(ev.get("image"), str):
                out["image_info"] = self._image_info(job, ev["image"])
            if ev.get("n") == 1 and log["context"]:
                ctx = dict(log["context"])
                ctx["image"] = self._image_info(job, ctx["image"]) if ctx.get("image") else None
                out["trace_context"] = ctx
            return out
        return ev

    # ------------------------------------------------------------------ results

    def bench(self, split: str, query: dict | None = None) -> Response:
        return json_response(res.bench_metrics(self.sources(), split))

    def realsets(self) -> Response:
        return json_response({"runs": res.realset_runs(self.sources())})

    def realset(self, run: str) -> Response:
        data = res.realset_payload(self.sources(), run, lambda rel: f"/api/results/realset/{run}/thumb/{rel}")
        return json_response(data) if data else error(404, "not_found", f"no real-set run {run!r}")

    def realset_item(self, run: str, sha: str, mode: str) -> Response:
        view = res.realset_item_view(self.sources(), run, sha, mode,
                                     lambda rel: f"/api/results/realset/{run}/files/{rel}")
        return json_response(view) if view else error(404, "not_found", "no such item")

    def realset_file(self, run: str, rel: str) -> Response:
        p = res.resolve_file(self.sources(), run, rel)
        return file_response(p) if p else error(404, "not_found", "no such file")

    def realset_thumb(self, run: str, rel: str) -> Response:
        p = res.thumb_for(self.sources(), run, rel, cache_dir(self.root))
        return file_response(p) if p else error(404, "not_found", "no such image")

    # ------------------------------------------------------------------ labelling

    def _session(self, pass_no: int | None) -> LabelSession | None:
        if self.label is not None:
            return self.label
        if not self.demo:
            return None
        pass_no = 2 if pass_no == 2 else 1
        with self._lock:
            if pass_no not in self._demo_labels:
                # The demo real set's label files (same format as `realset label` writes), but the
                # labels go to a scratch file so the demo's own labels.jsonl stays as built.
                scratch = self.root / "out" / "demo-labels.jsonl"
                manifest = self.demo_dir / "data" / "realset" / demomod.REALSET_SPLIT / f"label-pass{pass_no}.json"
                if manifest.exists():
                    session = LabelSession.from_label_file(manifest)
                    session.labels_path = scratch
                elif pass_no == 1:
                    session = LabelSession(items_from_dir(self.samples_dir), scratch, 1)
                else:
                    return None
                self._demo_labels[pass_no] = session
            return self._demo_labels[pass_no]

    @staticmethod
    def _pass_from(query: dict) -> int | None:
        try:
            return int((query.get("pass") or ["1"])[0])
        except ValueError:
            return 1

    def label_session(self, query: dict) -> Response:
        session = self._session(self._pass_from(query))
        if session is None:
            return error(404, "no_label_session", "label mode is not running; start it with "
                                                  "`printready realset label DIR`")
        view = session.view()
        view["demo"] = self.label is None
        return json_response(view)

    def label_image(self, sha: str) -> Response:
        sessions = [self.label] if self.label else list(self._demo_labels.values())
        for s in sessions:
            item = s.item_for(sha) if s else None
            if item:
                data, ctype = s.image_bytes(item)  # pass 2: the proof without its size caption
                return Response(200, data, ctype, {"Cache-Control": "no-cache"})
        return error(404, "not_found", "no such image in this session")

    def label_post(self, body: Any) -> Response:
        if not isinstance(body, dict):
            return error(400, "bad_request", "send {index, label}")
        session = self._session(body.get("pass") if isinstance(body.get("pass"), int) else None)
        if session is None:
            return error(404, "no_label_session", "label mode is not running")
        if self.label is not None and body.get("pass") not in (None, session.pass_no):
            return error(409, "wrong_pass", f"this session is pass {session.pass_no}")
        try:
            row = session.record(body.get("index"), body.get("label"))
        except LabelError as exc:
            return error(400, "bad_label", str(exc))
        view = session.view()
        return json_response({"row": row, "done": view["done"], "total": view["total"]}, 201)

    def shutdown(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


def iter_routes(app: App) -> Iterator[str]:  # for debugging / docs
    for m, p, _, label_ok in app.routes:
        yield f"{m} {p.pattern}{' (label mode)' if label_ok else ''}"
