"""Static export: a self-contained folder that opens from file:// (no modules, no fetch, no CDN)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest

from printready.web import state as webstate
from printready.web.export import ExportError, build_site, bundle_js

URL = re.compile(r"""https?://[^\s"'<>)\\]+""")
SVG_NS = "http://www.w3.org/2000/svg"


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("export") / "site"
    summary = build_site(out, demo=True, root=out.parent)
    return out, summary


def load_data(site_dir):
    text = (site_dir / "static" / "data.js").read_text(encoding="utf-8")
    assert text.startswith("window.PRINTREADY_STATIC = ")
    return json.loads(text[len("window.PRINTREADY_STATIC = "):].rstrip().rstrip(";"))


def test_files_exist(site):
    out, summary = site
    for rel in ("index.html", "static/app.js", "static/data.js", "static/favicon.svg", "static/css/tokens.css",
                "static/css/base.css", "static/css/components.css", "static/css/screens.css", ".nojekyll"):
        assert (out / rel).is_file(), rel
    assert summary["samples"] > 0 and summary["files"] > 10


def test_index_uses_classic_scripts(site):
    out, _ = site
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'type="module"' not in html
    assert html.index("static/data.js") < html.index("static/app.js")


def test_no_external_urls(site):
    """Nothing loads from the network. The only URLs are the SVG namespace and the profile's
    citations (links to the Sticker Mule FAQ pages the rules paraphrase)."""
    out, _ = site
    citations = {r["source"] for r in webstate.profile_payload()["rules"] if r["source"].startswith("http")}
    for path in out.rglob("*"):
        if path.suffix not in (".html", ".js", ".css", ".json", ".svg"):
            continue
        text = path.read_text(encoding="utf-8")
        for url in URL.findall(text):
            assert url == SVG_NS or url in citations, f"{path.name}: {url}"
        if path.suffix in (".html", ".css"):
            assert not re.search(r"""(src|href)\s*=\s*["']https?:""", text)
            assert "url(http" not in text and "@import" not in text


def test_every_referenced_file_is_in_the_folder(site):
    out, _ = site
    text = (out / "static" / "data.js").read_text(encoding="utf-8")
    refs = set(re.findall(r'"(data/[^"]+)"', text))
    assert refs
    missing = [r for r in refs if not (out / r).is_file()]
    assert not missing, missing[:5]


def test_data_shape(site):
    out, _ = site
    data = load_data(out)
    assert data["state"]["static"] is True
    assert data["runs"] and data["examples"]
    run = next(iter(data["runs"].values()))
    assert run["readonly"] is True and run["images"]["original"]["url"].startswith("data/")
    if run["cutline"]:
        assert "<svg" in data["texts"][run["cutline"]["url"]]
    assert data["realset"] and data["items"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_bundle_parses(site):
    out, _ = site
    result = subprocess.run(["node", "--check", str(out / "static" / "app.js")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_bundler_rewrites_imports_and_exports(tmp_path):
    (tmp_path / "a.js").write_text('export const greet = (x) => "hi " + x;\nexport function twice(f, x) { return f(f(x)); }\n',
                                   encoding="utf-8")
    (tmp_path / "app.js").write_text('import { greet, twice as t } from "./a.js";\nwindow.out = t(greet, "you");\n',
                                     encoding="utf-8")
    code = bundle_js(tmp_path, "app.js")
    assert "import " not in code and "export " not in code
    assert code.index('__m["a.js"]') < code.index('__m["app.js"]')
    assert "twice: t" in code
    if shutil.which("node"):
        js = "const window = {};\n" + code + "\nif (window.out !== 'hi hi you') throw new Error(window.out);"
        result = subprocess.run(["node", "-e", js], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr


def test_bundler_refuses_unsupported_syntax(tmp_path):
    (tmp_path / "app.js").write_text("export default 1;\n", encoding="utf-8")
    with pytest.raises(ExportError):
        bundle_js(tmp_path, "app.js")


def test_refuses_to_replace_an_unrelated_folder(tmp_path):
    target = tmp_path / "precious"
    target.mkdir()
    (target / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(ExportError):
        build_site(target, demo=True, root=tmp_path)
    assert (target / "notes.txt").exists()
