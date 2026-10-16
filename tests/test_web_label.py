"""Blind label mode: only label routes exist, labels.jsonl rows follow the schema exactly."""

from __future__ import annotations

import hashlib
import inspect
import json
import http.client

import pytest
from PIL import Image

from printready.web.label import PASS_LABELS, LabelItem, LabelSession, proof_items
from printready.web.server import AppConfig, serve, start_in_thread

ROW_KEYS = ["ts", "pass", "image", "proof", "label"]


def make_png(path, colour):
    Image.new("RGB", (80, 60), colour).save(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_pass_file(split_dir, n, items):
    data = {"pass": n, "caption": "3 in die-cut sticker", "keys": {}, "labels": "labels.jsonl", "items": items}
    (split_dir / f"label-pass{n}.json").write_text(json.dumps(data), encoding="utf-8")
    return split_dir / f"label-pass{n}.json"


@pytest.fixture()
def split_dir(tmp_path):
    d = tmp_path / "data" / "realset" / "test"
    (d / "label-images").mkdir(parents=True)
    items = []
    for colour in ("red", "green", "blue"):
        sha = make_png(d / "label-images" / f"tmp-{colour}.png", colour)
        (d / "label-images" / f"tmp-{colour}.png").rename(d / "label-images" / f"{sha}.png")
        items.append({"image": sha, "proof": None, "file": f"label-images/{sha}.png"})
    write_pass_file(d, 1, items)
    return d


class Client:
    def __init__(self, port):
        self.port = port

    def req(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {"Host": f"127.0.0.1:{self.port}"}
        raw = None
        if body is not None:
            raw = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=raw, headers=headers)
        r = conn.getresponse()
        data = r.read()
        conn.close()
        return r.status, data


@pytest.fixture()
def label_server(split_dir):
    session = LabelSession.from_label_file(split_dir / "label-pass1.json")
    server, app, _ = start_in_thread(AppConfig(root=split_dir, label=session, quiet=True))
    yield Client(server.server_address[1]), split_dir
    server.shutdown()
    server.server_close()
    app.shutdown()


def test_serve_signature_matches_realset_label():
    params = inspect.signature(serve).parameters
    assert {"label_dir", "label_pass", "open_browser", "port"} <= set(params)


def test_label_mode_refuses_every_other_route(label_server):
    c, _ = label_server
    for method, path in (("GET", "/api/state"), ("GET", "/api/runs"), ("GET", "/api/results/bench/dev"),
                         ("GET", "/api/results/realset"), ("GET", "/api/samples/mascot/image")):
        status, _ = c.req(method, path)
        assert status == 404, path
    status, _ = c.req("POST", "/api/runs", {"sample_id": "mascot"})
    assert status == 404
    status, html = c.req("GET", "/")
    assert status == 200 and b'<meta name="printready-mode" content="label">' in html
    status, _ = c.req("GET", "/static/js/label.js")
    assert status == 200


def test_session_is_blind_and_keeps_the_file_order(label_server):
    c, d = label_server
    status, data = c.req("GET", "/api/label/session")
    view = json.loads(data)
    assert status == 200 and view["pass"] == 1 and view["total"] == 3 and view["done"] == 0
    assert view["caption"] == "3 in die-cut sticker"
    assert [k["key"] for k in view["keys"]] == ["1", "2", "3", "4"]
    assert [k["label"] for k in view["keys"]] == ["ready_diecut", "fixable_diecut", "scene", "needs_person"]
    order = [it["image"] for it in json.loads((d / "label-pass1.json").read_text())["items"]]
    assert [it["sha"] for it in view["items"]] == order
    for it in view["items"]:  # images by content hash only: no file names reach the page
        assert it["url"] == f"/api/label/image/{it['sha']}"
        status, body = c.req("GET", it["url"])
        assert status == 200 and hashlib.sha256(body).hexdigest() == it["sha"]
    assert c.req("GET", "/api/label/image/" + "0" * 64)[0] == 404


def test_labels_append_rows_in_the_schema(label_server):
    c, d = label_server
    status, body = c.req("POST", "/api/label", {"index": 0, "label": "fixable_diecut", "pass": 1})
    assert status == 201, body
    status, _ = c.req("POST", "/api/label", {"index": 1, "label": "scene", "pass": 1})
    assert status == 201
    # undo then relabel: append-only, the last line per image wins
    status, body = c.req("POST", "/api/label", {"index": 0, "label": "needs_person", "pass": 1})
    assert status == 201 and json.loads(body)["done"] == 2
    lines = (d / "labels.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    rows = [json.loads(line) for line in lines]
    for row in rows:
        assert list(row) == ROW_KEYS
        assert row["pass"] == 1 and row["proof"] is None and row["label"] in PASS_LABELS[1]
        assert row["ts"].endswith("Z") and len(row["image"]) == 64
    view = json.loads(c.req("GET", "/api/label/session")[1])
    assert view["items"][0]["label"] == "needs_person" and view["items"][1]["label"] == "scene"
    assert view["start"] == 2


@pytest.mark.parametrize("body", [
    {"index": 0, "label": "fixable"},  # the old three-way label is no longer a pass-1 label
    {"index": 0, "label": "acceptable"},
    {"index": 9, "label": "scene"},
    {"index": "0", "label": "scene"},
    {"label": "scene"},
])
def test_bad_labels_are_refused(label_server, body):
    c, d = label_server
    status, _ = c.req("POST", "/api/label", body)
    assert status == 400
    assert not (d / "labels.jsonl").exists()


def test_wrong_pass_is_refused(label_server):
    c, _ = label_server
    status, _ = c.req("POST", "/api/label", {"index": 0, "label": "acceptable", "pass": 2})
    assert status == 409


def test_pass_two_shows_each_proof_once(tmp_path):
    a = make_png(tmp_path / "a.png", "red")
    proof = tmp_path / "proof.png"
    make_png(proof, "white")
    dup = tmp_path / "proof-copy.png"
    dup.write_bytes(proof.read_bytes())  # bit-identical proof from the other mode
    items = proof_items([(a, proof), (a, dup)])
    assert len(items) == 1
    session = LabelSession(items, tmp_path / "labels.jsonl", 2)
    view = session.view()
    assert view["caption"] is None and [k["key"] for k in view["keys"]] == ["y", "n"]
    row = session.record(0, "acceptable")
    assert list(row) == ROW_KEYS and row["pass"] == 2 and row["proof"] == items[0].proof and row["image"] == a


def test_pass_two_from_the_realset_file(tmp_path):
    proof_sha = make_png(tmp_path / "p.png", "white")
    write_pass_file(tmp_path, 2, [{"image": "a" * 64, "proof": proof_sha, "file": "p.png"},
                                  {"image": "b" * 64, "proof": proof_sha, "file": "p.png"}])
    session = LabelSession.from_label_file(tmp_path / "label-pass2.json")
    assert len(session.items) == 1 and session.pass_no == 2 and session.caption is None
    assert session.labels_path == tmp_path / "labels.jsonl"


def test_items_without_a_proof_cannot_be_pass_two(tmp_path):
    with pytest.raises(ValueError):
        LabelSession([LabelItem("a" * 64, None, tmp_path / "x.png")], tmp_path / "l.jsonl", 2)
