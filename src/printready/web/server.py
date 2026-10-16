"""HTTP plumbing for the workbench: stdlib ThreadingHTTPServer bound to 127.0.0.1.

Request hygiene for a local server that can start paid runs:
- binds 127.0.0.1 only;
- rejects requests whose Host is not a loopback name (DNS-rebinding guard);
- POST must be application/json (so a cross-site form cannot send one without a CORS preflight,
  which this server never answers) and, if an Origin is sent, it must be this server;
- request bodies are capped (base64 of a 20 MB image plus JSON).
"""

from __future__ import annotations

import json
import sys
import threading
import webbrowser
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from printready.web.api import MAX_BODY_BYTES, App, Response, error
from printready.web.label import LabelSession
from printready.web.paths import default_out_dir

HOST = "127.0.0.1"
LOOPBACK_NAMES = {"127.0.0.1", "localhost", "[::1]"}


@dataclass
class AppConfig:
    root: Path = field(default_factory=Path.cwd)
    out_dir: Path | None = None
    demo: bool = False
    demo_speed: float = 1.0
    label: LabelSession | None = None
    demo_dir: Path | None = None
    samples_dir: Path | None = None
    quiet: bool = False
    show_test: bool = False  # blinding: the real-set test split stays hidden unless this is set

    def build(self) -> App:
        return App(root=self.root, out_dir=self.out_dir or default_out_dir(self.root), demo=self.demo,
                   demo_speed=self.demo_speed, label=self.label, demo_dir=self.demo_dir, samples_dir=self.samples_dir,
                   show_test=self.show_test)


class Handler(BaseHTTPRequestHandler):
    server_version = "printready"
    app: App  # set on the subclass made in make_server
    quiet = False

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        name = host.rsplit(":", 1)[0] if not host.startswith("[") else host.split("]")[0] + "]"
        return name in LOOPBACK_NAMES

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin or origin == "null":  # same-origin fetches may omit it; file:// sends "null"
            return origin is None
        parts = urlsplit(origin)
        return parts.hostname in {"127.0.0.1", "localhost", "::1"} and parts.port == self.server.server_address[1]

    def _dispatch(self, method: str) -> None:
        try:
            if not self._host_ok():
                return self._send(error(403, "bad_host", "this server only answers on 127.0.0.1"))
            parts = urlsplit(self.path)
            path = unquote(parts.path)
            query = parse_qs(parts.query)
            body = None
            if method == "POST":
                if not self._origin_ok():
                    return self._send(error(403, "bad_origin", "cross-origin requests are not allowed"))
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
                if ctype != "application/json":
                    return self._send(error(415, "bad_content_type", "send application/json"))
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY_BYTES:
                    return self._send(error(413, "too_large", "the request is over the 20 MB upload limit"))
                raw = self.rfile.read(length) if length else b""
                try:
                    body = json.loads(raw or b"null")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return self._send(error(400, "bad_json", "the body is not valid JSON"))
            self._send(self.app.handle(method, path, query, body))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass  # the browser went away (closed tab, EventSource.close())

    def _send(self, resp: Response) -> None:
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in resp.headers.items():
            self.send_header(k, v)
        if resp.stream is None:
            self.send_header("Content-Length", str(len(resp.body)))
            self.end_headers()
            if resp.body and self.command != "HEAD":
                self.wfile.write(resp.body)
            return
        self.send_header("Connection", "close")
        self.end_headers()

        def write(chunk: bytes) -> None:
            self.wfile.write(chunk)
            self.wfile.flush()

        resp.stream(write)
        self.close_connection = True

    def log_request(self, code="-", size="-") -> None:
        if self.quiet:
            return
        path = self.path.split("?")[0]
        if path.startswith("/static/") or "/files/" in path or "/thumb" in path or path.endswith("/image"):
            return  # keep the console readable: API calls only
        sys.stderr.write(f"  {self.command} {path} {code}\n")

    def log_message(self, fmt: str, *args) -> None:
        if not self.quiet:
            super().log_message(fmt, *args)


class Server(ThreadingHTTPServer):
    daemon_threads = True  # SSE readers never block shutdown
    allow_reuse_address = False  # Windows: reuse would let two servers share a port


def make_server(config: AppConfig, port: int = 8765) -> tuple[Server, App]:
    app = config.build()
    handler = type("BoundHandler", (Handler,), {"app": app, "quiet": config.quiet})
    server = Server((HOST, port), handler)
    return server, app


def start_in_thread(config: AppConfig, port: int = 0) -> tuple[Server, App, threading.Thread]:
    """Tests: a server on a free port, serving in a daemon thread."""
    server, app = make_server(config, port)
    t = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    t.start()
    return server, app, t


def run_server(config: AppConfig, port: int = 8765, open_browser: bool = False) -> int:
    try:
        server, app = make_server(config, port)
    except OSError as exc:
        print(f"printready serve: cannot listen on {HOST}:{port} ({exc.strerror or exc}). "
              f"Try --port {port + 1}.", file=sys.stderr)
        return 1
    url = f"http://{HOST}:{server.server_address[1]}/"
    if config.label is not None:
        mode = f"label mode, pass {config.label.pass_no}, {len(config.label.items)} images -> {config.label.labels_path}"
    else:
        mode = "demo (simulated runs, nothing charged)" if config.demo else "live"
    print(f"printready workbench: {url}  [{mode}]  Ctrl+C to stop", flush=True)
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        app.shutdown()
        server.server_close()
    return 0


def serve(label_dir: Path | None = None, label_pass: int = 1, open_browser: bool = True, port: int = 8765,
          demo: bool = False) -> int:
    """Start the workbench; with `label_dir`, start blind label mode instead.

    `printready realset label --split S --pass N` calls serve(label_dir=data/realset/S, label_pass=N):
    the items come from label_dir/label-pass{N}.json and labels are appended to the labels.jsonl it
    names (label_dir/labels.jsonl). In label mode every non-label route is a 404.
    """
    from printready.web.label import LabelSession

    if label_dir is None:
        return run_server(AppConfig(demo=demo), port=port, open_browser=open_browser)
    manifest = Path(label_dir) / f"label-pass{int(label_pass)}.json"
    if not manifest.exists():
        print(f"printready label mode: {manifest} not found", file=sys.stderr)
        return 2
    session = LabelSession.from_label_file(manifest)
    return run_server(AppConfig(root=Path.cwd(), label=session), port=port, open_browser=open_browser)

