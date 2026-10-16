"""Workbench API: server in a thread, the demo runner at speed 0 (no model calls, no network)."""

from __future__ import annotations

import base64
import io
import json
import http.client
import threading

import pytest
from PIL import Image, ImageDraw

from printready.web.server import AppConfig, start_in_thread

OUTCOMES = {"ready", "fixable", "needs_person"}


class Client:
    def __init__(self, port: int):
        self.port = port

    def request(self, method: str, path: str, body=None, headers=None, raw: bytes | None = None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        hdrs = {"Host": f"127.0.0.1:{self.port}"}
        if body is not None:
            raw = json.dumps(body).encode()
            hdrs["Content-Type"] = "application/json"
        hdrs.update(headers or {})
        conn.request(method, path, body=raw, headers=hdrs)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, resp.getheader("Content-Type") or "", data

    def json(self, method: str, path: str, body=None, headers=None):
        status, _, data = self.request(method, path, body, headers)
        return status, json.loads(data) if data else None

    def events(self, run_id: str) -> list[dict]:
        """Read the SSE stream to its end and return the events."""
        status, ctype, data = self.request("GET", f"/api/runs/{run_id}/events")
        assert status == 200 and ctype.startswith("text/event-stream")
        out = []
        for block in data.decode().split("\n\n"):
            fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
            if fields.get("event") in ("findings", "step", "turn", "done", "error"):
                out.append(json.loads(fields["data"]))
        return out


@pytest.fixture()
def demo_server(tmp_path):
    server, app, _ = start_in_thread(AppConfig(root=tmp_path, demo=True, demo_speed=0, quiet=True))
    yield Client(server.server_address[1]), tmp_path
    server.shutdown()
    server.server_close()
    app.shutdown()


def png_b64(size=(240, 200), colour="#ff8800", bg=(255, 255, 255)) -> str:
    img = Image.new("RGB", size, bg)
    ImageDraw.Draw(img).ellipse((40, 30, size[0] - 40, size[1] - 30), fill=colour, outline="black", width=4)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_index_and_state(demo_server):
    c, _ = demo_server
    status, ctype, html = c.request("GET", "/")
    assert status == 200 and "text/html" in ctype
    assert b'content="app"' in html and b"static/js/app.js" in html
    status, state = c.json("GET", "/api/state")
    assert status == 200
    assert state["demo"] is True and state["mode"] == "app"
    keys = {r["key"] for r in state["profile"]["rules"]}
    assert {"ppi_target", "border_in", "soft_alpha_max_in"} <= keys
    assert state["profile"]["label"] == "Sticker Mule die-cut rules (paraphrased from public FAQ)"
    assert [m["id"] for m in state["models"]][:2] == ["xai:grok-4.3", "xai:grok-4.7"]
    assert state["spend"]["total_usd"] == 0 and state["spend"]["cap_usd"] > 0
    assert state["samples"] and all(s["image"].startswith("/api/samples/") for s in state["samples"])


def test_spend_meter_reads_the_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTREADY_SPEND_CAP_USD", "7.5")
    ledger = tmp_path / "results" / "spend-ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"usd": 0.5}\n{"usd": 0.25}\nnot json\n{"tokens_in": 3}\n', encoding="utf-8")
    server, app, _ = start_in_thread(AppConfig(root=tmp_path, demo=True, demo_speed=0, quiet=True))
    try:
        _, state = Client(server.server_address[1]).json("GET", "/api/state")
        assert state["spend"]["total_usd"] == pytest.approx(0.75)
        assert state["spend"]["cap_usd"] == pytest.approx(7.5)
    finally:
        server.shutdown()
        server.server_close()
        app.shutdown()


def test_demo_rules_run_streams_then_done(demo_server):
    c, root = demo_server
    status, body = c.json("POST", "/api/runs", {"sample_id": "mascot", "size_in": 3, "mode": "rules", "vision": True})
    assert status == 201, body
    run_id = body["run_id"]
    events = c.events(run_id)
    types = [e["type"] for e in events]
    assert types[0] == "findings" and types[-1] == "done"
    assert "step" in types
    steps = [e for e in events if e["type"] == "step"]
    assert all(e["preview_info"]["url"].startswith(f"/api/runs/{run_id}/files/") for e in steps if e.get("preview"))
    result = events[-1]["result"]
    assert result["outcome"] in OUTCOMES
    assert {"mode", "art", "before", "after", "outputs", "customer_message"} <= set(result)

    status, view = c.json("GET", f"/api/runs/{run_id}")
    assert status == 200 and view["status"] == "done"
    assert view["images"]["fixed"] and view["images"]["original"] and view["cutline"]
    names = {d["name"] for d in view["downloads"]}
    assert {"fixed.png", "cutline.svg", "proof.png", "report.json"} <= names
    status, ctype, data = c.request("GET", view["images"]["proof"]["url"])
    assert status == 200 and ctype == "image/png" and data[:4] == b"\x89PNG"
    assert (root / "out" / "workbench" / run_id / "run.json").exists()

    _, runs = c.json("GET", "/api/runs")
    assert runs["runs"][0]["id"] == run_id and runs["runs"][0]["outcome"] == result["outcome"]

    # a reconnecting client asks for the events after the ones it has
    status, _, tail = c.request("GET", f"/api/runs/{run_id}/events?from={len(events) - 1}")
    assert tail.count(b"event: done") == 1 and b"event: step" not in tail


def test_demo_agent_run_streams_turns(demo_server):
    c, _ = demo_server
    status, body = c.json("POST", "/api/runs", {"sample_id": "badge", "size_in": 3, "mode": "agent", "model": "xai:grok-4.3"})
    assert status == 201
    events = c.events(body["run_id"])
    turns = [e for e in events if e["type"] == "turn"]
    assert turns and turns[0]["n"] == 1
    for t in turns:
        assert {"text", "tool_calls", "tokens", "cost_usd", "latency_ms"} <= set(t)
    assert turns[-1]["tool_calls"][-1]["name"] in ("finish", "handoff")
    assert events[-1]["type"] == "done"
    _, view = c.json("GET", f"/api/runs/{body['run_id']}")
    assert len(view["turns"]) == len(turns) and view["mode"] == "agent"


def test_upload_runs_the_real_pipeline(demo_server):
    c, _ = demo_server
    status, body = c.json("POST", "/api/runs", {"image_b64": png_b64(), "filename": "../../evil name.png",
                                                "size_in": 2, "mode": "rules"})
    assert status == 201, body
    events = c.events(body["run_id"])
    assert events[-1]["type"] == "done", events[-1]
    _, view = c.json("GET", f"/api/runs/{body['run_id']}")
    assert view["filename"] == "evil name.png"  # path parts are stripped
    assert view["result"]["spec"]["size_in"] == 2


@pytest.mark.parametrize("payload, status", [
    ({"image_b64": base64.b64encode(b"GIF89a" + b"\0" * 64).decode(), "size_in": 3}, 415),
    ({"image_b64": "not base64!!", "size_in": 3}, 400),
    ({"sample_id": "mascot", "size_in": 0.1}, 400),
    ({"sample_id": "mascot", "size_in": 3, "mode": "magic"}, 400),
    ({"sample_id": "mascot", "size_in": 3, "mode": "agent", "model": "xai:unknown"}, 400),
    ({"sample_id": "nope", "size_in": 3}, 404),
    ({"size_in": 3}, 400),
])
def test_bad_run_requests(demo_server, payload, status):
    c, _ = demo_server
    got, body = c.json("POST", "/api/runs", payload)
    assert got == status and body["error"]


def test_upload_over_20_mb_is_refused(demo_server):
    c, _ = demo_server
    blob = b"\x89PNG\r\n\x1a\n" + b"\0" * 20_000_100
    status, body = c.json("POST", "/api/runs", {"image_b64": base64.b64encode(blob).decode(), "size_in": 3})
    assert status == 413 and "20 MB" in body["message"]


def test_request_hygiene(demo_server):
    c, _ = demo_server
    # cross-site form posts: wrong content type, foreign origin, foreign host
    status, _, _ = c.request("POST", "/api/runs", raw=b"{}", headers={"Content-Type": "text/plain"})
    assert status == 415
    status, _ = c.json("POST", "/api/runs", {"sample_id": "mascot"}, headers={"Origin": "http://evil.example"})
    assert status == 403
    status, _, _ = c.request("GET", "/api/state", headers={"Host": "evil.example"})
    assert status == 403
    status, _, _ = c.request("POST", "/api/runs", raw=b"{not json", headers={"Content-Type": "application/json"})
    assert status == 400


def test_no_path_traversal(demo_server):
    c, _ = demo_server
    _, body = c.json("POST", "/api/runs", {"sample_id": "bolt", "size_in": 3, "mode": "rules"})
    c.events(body["run_id"])
    for path in (f"/api/runs/{body['run_id']}/files/..%2Frun.json", "/static/../api.py", "/static/..%2F..%2Fapi.py",
                 "/api/results/realset/demo/files/..%2F..%2F..%2Findex.json", "/api/runs/..%2F..%2Fpyproject.toml"):
        status, _, _ = c.request("GET", path)
        assert status == 404, path


def test_results_endpoints(demo_server):
    c, _ = demo_server
    status, state = c.json("GET", "/api/state")
    runs = state["results"]["realset_runs"]
    demo_runs = [r for r in runs if r["demo"]]
    assert demo_runs, runs
    status, rs = c.json("GET", f"/api/results/realset/{demo_runs[0]['id']}")
    assert status == 200 and rs["items"]
    card = rs["items"][0]
    assert card["original"] and set(card["modes"]) <= {"rules", "agent"}
    mode = next(iter(card["modes"]))
    status, view = c.json("GET", f"/api/results/realset/{rs['run']}/items/{card['image']}/{mode}")
    assert status == 200 and view["readonly"] is True and view["result"]["outcome"] in OUTCOMES
    status, ctype, _ = c.request("GET", card["original"])
    assert status == 200 and ctype == "image/png"
    status, bench = c.json("GET", "/api/results/bench/dev")
    assert status == 200 and "available" in bench


def test_live_mode_spend_guard_refuses_before_any_call(tmp_path, monkeypatch):
    monkeypatch.setenv("PRINTREADY_SPEND_CAP_USD", "1.00")
    ledger = tmp_path / "results" / "spend-ledger.jsonl"
    ledger.parent.mkdir(parents=True)
    ledger.write_text('{"usd": 0.999}\n', encoding="utf-8")
    server, app, _ = start_in_thread(AppConfig(root=tmp_path, demo=False, quiet=True))
    try:
        c = Client(server.server_address[1])
        status, body = c.json("POST", "/api/runs", {"sample_id": "mascot", "size_in": 3, "mode": "agent"})
        assert status == 402 and body["error"] == "budget"
        assert not (tmp_path / "out" / "workbench").exists() or not any((tmp_path / "out" / "workbench").iterdir())
    finally:
        server.shutdown()
        server.server_close()
        app.shutdown()


def test_server_binds_loopback_only(demo_server):
    c, _ = demo_server
    from printready.web.server import HOST

    assert HOST == "127.0.0.1"


def test_concurrent_sse_readers(demo_server):
    c, _ = demo_server
    _, body = c.json("POST", "/api/runs", {"sample_id": "cloud", "size_in": 3, "mode": "rules", "vision": True})
    results = []
    threads = [threading.Thread(target=lambda: results.append(c.events(body["run_id"]))) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert len(results) == 3 and all(r and r[-1]["type"] == "done" for r in results)
    assert len({len(r) for r in results}) == 1


def test_text_boxes_come_back_in_pixels(demo_server):
    c, _ = demo_server
    _, body = c.json("POST", "/api/runs", {"sample_id": "badge", "size_in": 3, "mode": "rules", "vision": True})
    c.events(body["run_id"])
    _, view = c.json("GET", f"/api/runs/{body['run_id']}")
    boxes = view["text_boxes"]
    assert boxes and any(b["status"] == "fail" for b in boxes)
    w, h = view["result"]["art"]["width"], view["result"]["art"]["height"]
    for b in boxes:
        x0, y0, x1, y1 = b["box"]
        assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h


def test_a_running_view_never_shows_final_outputs(tmp_path):
    """Until `done`, fixed.png, the cut line and the downloads stay hidden, even if the files
    already exist (a replay, or a pipeline that writes early)."""
    from printready.web.runs import build_view

    (tmp_path / "original.png").write_bytes(base64.b64decode(png_b64()))
    for name in ("fixed.png", "proof.png"):
        (tmp_path / name).write_bytes(base64.b64decode(png_b64()))
    (tmp_path / "cutline.svg").write_text('<svg viewBox="0 0 1 1"></svg>', encoding="utf-8")
    record = {"id": "x", "status": "running", "original": "original.png", "spec": {"size_in": 3}}
    view = build_view(tmp_path, record, lambda n: n, [])
    assert view["images"]["original"] and not view["images"]["fixed"] and not view["images"]["proof"]
    assert view["cutline"] is None and view["downloads"] == []
    view = build_view(tmp_path, {**record, "status": "done"}, lambda n: n, [])
    assert view["images"]["fixed"] and view["cutline"]


def test_trace_reads_context_and_tool_model_calls_from_the_agent_log(tmp_path):
    """The Trace's context card and per-turn sub-calls come from log.jsonl: the read_text vision
    call made inside turn 1's tools belongs to turn 1, not turn 2."""
    from printready.web.runs import build_view

    log = [
        {"type": "start", "model": "xai:grok-4.3", "max_turns": 8, "tools": ["check", "read_text", "finish"],
         "system_prompt": "You prepare sticker art.", "image": "look-0-upload.png"},
        {"type": "call", "purpose": "agent", "tokens_in": 3000, "cost_usd": 0.004, "status": "ok"},
        {"type": "call", "purpose": "vision", "model": "xai:grok-4.3", "tokens_in": 1200, "tokens_cached": 0,
         "tokens_out": 90, "cost_usd": 0.002, "latency_ms": 2100, "status": "ok"},
        {"type": "turn", "n": 1},
        {"type": "call", "purpose": "agent", "tokens_in": 3400, "cost_usd": 0.004, "status": "ok"},
        {"type": "turn", "n": 2},
    ]
    (tmp_path / "log.jsonl").write_text("\n".join(json.dumps(r) for r in log) + "\n", encoding="utf-8")
    turn = {"type": "turn", "text": "", "tool_calls": [], "tokens": {"in": 3000, "cached": 0, "out": 40},
            "cost_usd": 0.004, "latency_ms": 900}
    events = [{**turn, "n": 1}, {**turn, "n": 2}]
    view = build_view(tmp_path, {"id": "x", "status": "running", "mode": "agent", "spec": {"size_in": 3}},
                      lambda n: n, events)
    ctx = view["trace_context"]
    assert ctx["model"] == "xai:grok-4.3" and ctx["max_turns"] == 8 and "read_text" in ctx["tools"]
    assert [t["n"] for t in view["turns"]] == [1, 2]
    assert [c["purpose"] for c in view["turns"][0]["sub_calls"]] == ["vision"]
    assert view["turns"][0]["sub_calls"][0]["latency_ms"] == 2100
    assert view["turns"][1]["sub_calls"] == []


def test_real_example_notices_match_the_mode(demo_server):
    """Real Grok examples (dev set) say so, and a rules replay does not claim model turns."""
    c, _ = demo_server
    _, state = c.json("GET", "/api/state")
    real = [s for s in state["samples"] if s.get("group") == "real"]
    if not real:
        pytest.skip("no real examples in the demo folder")
    for mode in ("rules", "agent"):
        status, body = c.json("POST", "/api/runs", {"sample_id": real[0]["id"], "size_in": 3, "mode": mode,
                                                     "vision": True, "model": "xai:grok-4.3"})
        assert status == 201, body
        c.events(body["run_id"])
        _, view = c.json("GET", f"/api/runs/{body['run_id']}")
        text = " ".join(view.get("notices") or [])
        assert "Real Grok output, dev set" in text
        assert ("model turn" in text) == (mode == "agent")
        assert view["status"] == "done" and view["result"]["mode"] == mode
