"""Results readers over the real layouts, and blinding: the test split stays out of the workbench
until it is asked for (`serve --show-test`, or naming it in `site build --realset`)."""

from __future__ import annotations

import http.client
import json
from pathlib import Path

import pytest
from PIL import Image

from printready.web import results as res
from printready.web.export import build_site
from printready.web.server import AppConfig, start_in_thread

SHAS = {"dev": "d" * 64, "test": "e" * 64}


def _write_split(root: Path, split: str) -> None:
    sha = SHAS[split]
    data = root / "data" / "realset" / split
    data.mkdir(parents=True)
    Image.new("RGB", (40, 40), "#3a7").save(data / "img.png")
    (data / "manifest.jsonl").write_text(
        json.dumps({"sha256": sha, "file": "img.png", "model": "xai:grok-imagine-image", "prompt": f"{split} prompt"}) + "\n",
        encoding="utf-8")
    out_rel = f"results/realset/{split}/rules/{sha}"
    run = root / out_rel
    run.mkdir(parents=True)
    Image.new("RGBA", (40, 40), (0, 0, 0, 0)).save(run / "proof.png")
    report = {"outcome": "fixable", "mode": "rules", "handoff_reason": None,
              "before": {"status": "warn", "findings": []}, "after": {"status": "pass", "findings": []}}
    (run / "report.json").write_text(json.dumps(report), encoding="utf-8")
    (root / "results" / "realset" / split / "rules" / "runs.jsonl").write_text(
        json.dumps({"image": sha, "outcome": "fixable", "out_dir": out_rel}) + "\n", encoding="utf-8")


@pytest.fixture()
def root(tmp_path):
    for split in ("dev", "test"):
        _write_split(tmp_path, split)
    return tmp_path


def test_test_split_is_blind_by_default(root):
    sources = [res.Source(root)]
    assert [r["id"] for r in res.realset_runs(sources)] == ["dev"]
    assert res.realset_payload(sources, "test", str) is None
    assert res.realset_item_view(sources, "test", SHAS["test"], "rules", str) is None
    assert res.resolve_file(sources, "test", "data/realset/test/img.png") is None
    # nor reachable through the dev split
    assert res.resolve_file(sources, "dev", "data/realset/test/img.png") is None
    dev = res.realset_payload(sources, "dev", str)
    assert [c["image"] for c in dev["items"]] == [SHAS["dev"]]
    assert dev["items"][0]["modes"]["rules"]["outcome"] == "fixable"


def test_unblinding_is_explicit(root):
    sources = [res.Source(root, show_blind=True)]
    assert [r["id"] for r in res.realset_runs(sources)] == ["dev", "test"]
    assert res.realset_payload(sources, "test", str)["items"][0]["prompt"] == "test prompt"


class _Client:
    def __init__(self, port: int):
        self.port = port

    def get(self, path: str) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}"})
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body


@pytest.mark.parametrize("show_test", [False, True])
def test_server_hides_the_test_split_unless_asked(root, show_test):
    server, app, _ = start_in_thread(AppConfig(root=root, out_dir=root / "out", demo=False, quiet=True,
                                               show_test=show_test))
    try:
        c = _Client(server.server_address[1])
        status, body = c.get("/api/results/realset")
        assert status == 200
        ids = [r["id"] for r in json.loads(body)["runs"]]
        assert ids == (["dev", "test"] if show_test else ["dev"])
        assert c.get("/api/results/realset/dev")[0] == 200
        for path in ("/api/results/realset/test",
                     f"/api/results/realset/test/items/{SHAS['test']}/rules",
                     "/api/results/realset/test/files/data/realset/test/img.png",
                     "/api/results/realset/test/thumb/data/realset/test/img.png",
                     "/api/results/realset/dev/files/data/realset/test/img.png"):
            expected = 200 if show_test and path.startswith("/api/results/realset/test") else 404
            assert c.get(path)[0] == expected, path
        status, body = c.get("/api/state")
        assert status == 200 and (b'"test"' in body) == show_test
    finally:
        server.shutdown()
        server.server_close()
        app.shutdown()


def _site_data(site: Path) -> dict:
    text = (site / "static" / "data.js").read_text(encoding="utf-8")
    return json.loads(text[len("window.PRINTREADY_STATIC = "):].rstrip().rstrip(";"))


def test_export_includes_the_test_split_only_when_named(root, tmp_path_factory):
    default = tmp_path_factory.mktemp("site") / "default"
    build_site(default, root=root)
    blob = (default / "static" / "data.js").read_text(encoding="utf-8")
    assert SHAS["test"] not in blob and "test prompt" not in blob
    assert SHAS["dev"] in blob

    named = tmp_path_factory.mktemp("site") / "named"
    build_site(named, realset=root / "results" / "realset" / "test", root=root)
    blob = (named / "static" / "data.js").read_text(encoding="utf-8")
    assert SHAS["test"] in blob and SHAS["dev"] not in blob
    assert _site_data(named)
