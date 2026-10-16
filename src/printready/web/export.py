"""`printready site build`: a static, read-only copy of the workbench (Results plus saved runs).

Browsers refuse ES modules and fetch() on file:// pages, so the export
- bundles static/js/*.js into ONE classic script (bundle_js below: a tiny, convention-based
  bundler; every module uses one-line `import { a, b } from "./x.js";` and `export function|const|class`),
- writes all data into static/data.js as `window.PRINTREADY_STATIC = {...}` (api.js reads it), and
- copies the images next to it (data/...), downscaled where they are only previews.
No server, no API, no external URLs: it opens from file:// and from GitHub Pages.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Callable

from PIL import Image

from printready.web import demo as demomod
from printready.web import results as res
from printready.web import state as webstate
from printready.web.paths import STATIC_DIR, demo_dir, samples_dir
from printready.web.runs import build_view

IMPORT_RE = re.compile(r'^import\s*\{([^}]*)\}\s*from\s*"\./([\w.-]+\.js)";\s*$', re.M)
EXPORT_RE = re.compile(r"^export\s+((?:async\s+)?function\*?|class|const|let)\s+([A-Za-z_$][\w$]*)", re.M)
MAX_FULL_PX = 1600  # originals and fixed art above this are downscaled in the export
PREVIEW_PX = {"step-": 640, "look-": 512, "overlay": 800}


class ExportError(RuntimeError):
    pass


# ------------------------------------------------------------------ the JS bundler

def bundle_js(js_dir: Path = STATIC_DIR / "js", entry: str = "app.js") -> str:
    sources = {p.name: p.read_text(encoding="utf-8") for p in js_dir.glob("*.js")}
    if entry not in sources:
        raise ExportError(f"{entry} not found in {js_dir}")
    order: list[str] = []
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in order:
            return
        if name in visiting:
            raise ExportError(f"circular import through {name}")
        if name not in sources:
            raise ExportError(f"unknown module ./{name}")
        visiting.add(name)
        for _, dep in IMPORT_RE.findall(sources[name]):
            visit(dep)
        visiting.discard(name)
        order.append(name)

    visit(entry)
    parts = ["(function () {", '"use strict";', "const __m = {};"]
    for name in order:
        src = sources[name]
        if re.search(r"^\s*import\s", IMPORT_RE.sub("", src), re.M) or re.search(r"^export\s+(default|\{)", src, re.M):
            raise ExportError(f"{name}: only one-line named imports and `export function|const|class` are supported")
        lines = []
        for names, dep in IMPORT_RE.findall(src):
            binds = []
            for item in names.split(","):
                item = item.strip()
                if not item:
                    continue
                if " as " in item:
                    a, b = (x.strip() for x in item.split(" as "))
                    binds.append(f"{a}: {b}")
                else:
                    binds.append(item)
            lines.append(f"  const {{ {', '.join(binds)} }} = __m[{json.dumps(dep)}];")
        exported = [m.group(2) for m in EXPORT_RE.finditer(src)]
        body = EXPORT_RE.sub(lambda m: f"{m.group(1)} {m.group(2)}", IMPORT_RE.sub("", src))
        parts.append(f"// ---- {name}")
        parts.append(f"__m[{json.dumps(name)}] = (function () {{")
        parts.extend(lines)
        parts.append(body)
        parts.append(f"  return {{ {', '.join(exported)} }};")
        parts.append("})();")
    parts.append("})();")
    return "\n".join(parts) + "\n"


# ------------------------------------------------------------------ copying files

class Copier:
    """Copies source files into the site under stable names, downscaling previews."""

    def __init__(self, site: Path):
        self.site = site
        self.files = 0
        self.bytes = 0
        self._done: dict[str, str] = {}

    def copy(self, src: Path, rel: str) -> str:
        key = f"{src}|{rel}"
        if key in self._done:
            return self._done[key]
        dest = self.site / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        limit = next((px for prefix, px in PREVIEW_PX.items() if src.name.startswith(prefix)), MAX_FULL_PX)
        if src.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            with Image.open(src) as im:
                if max(im.size) > limit:
                    im = im.convert("RGBA") if im.mode not in ("RGB", "RGBA") else im
                    k = limit / max(im.size)
                    im = im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
                    im.save(dest)
                else:
                    shutil.copyfile(src, dest)
        else:
            shutil.copyfile(src, dest)
        self.files += 1
        self.bytes += dest.stat().st_size
        self._done[key] = rel
        return rel

    def thumb(self, src: Path, px: int = 360) -> str:
        digest = hashlib.sha256(f"{src}|{src.stat().st_mtime}".encode()).hexdigest()[:20]
        rel = f"data/thumbs/{digest}.png"
        dest = self.site / rel
        if not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(src) as im:
                im = im.convert("RGBA")
                im.thumbnail((px, px), Image.LANCZOS)
                im.save(dest, optimize=True)
            self.files += 1
            self.bytes += dest.stat().st_size
        return rel


def _strip_t(events: list[dict]) -> list[dict]:
    return [{k: v for k, v in e.items() if k != "_t"} for e in events]


def _with_files(make_view: Callable[[Callable[[str], str]], dict], resolve: Callable[[str], Path | None],
                copier: Copier, prefix: str, texts: dict) -> dict | None:
    """Build a RunView whose URLs point into the site, copying each referenced file."""
    mapping: dict[str, str] = {}

    def url(name: str) -> str:
        rel = f"{prefix}/{name}"
        mapping[rel] = name
        return rel

    view = make_view(url)
    if view is None:
        return None
    for rel, name in mapping.items():
        src = resolve(name)
        if src is not None and src.is_file():
            copier.copy(src, rel)
            if src.suffix == ".svg":
                texts[rel] = src.read_text(encoding="utf-8")
    return view


# ------------------------------------------------------------------ the build

def build_site(out: Path, *, realset: Path | None = None, bench: list[str] | None = None, demo: bool = False,
               root: Path | None = None) -> dict:
    root = Path(root or Path.cwd())
    out = Path(out)
    if out.exists():
        if not (out / "index.html").exists() and any(out.iterdir()):
            raise ExportError(f"{out} exists and does not look like a previous export; refusing to replace it")
        shutil.rmtree(out)
    (out / "static" / "css").mkdir(parents=True)
    copier = Copier(out)
    texts: dict[str, str] = {}

    sources: list[res.Source] = []
    split = None
    if realset is not None:
        realset = Path(realset).resolve()
        if realset.parent.name != "realset" or realset.parent.parent.name != "results":
            raise ExportError("--realset must be a results/realset/<split> folder")
        split = realset.name
        # naming a split explicitly (e.g. test, after pass 2) is what unblinds it
        sources.append(res.Source(realset.parents[2], show_blind=True))
    if demo:
        sources.append(res.Source(demo_dir(), demo=True))
    if not sources:
        sources.append(res.Source(root))

    # Results: benchmark
    bench_data = {}
    for item in res.bench_splits(sources):
        if bench and item["split"] not in bench:
            continue
        bench_data[item["split"]] = res.bench_metrics(sources, item["split"])

    # Results: real set (gallery + agreement) and every item as a read-only run
    realset_runs = [r for r in res.realset_runs(sources) if split is None or r["id"] == split or r["demo"]]
    realset_payloads, items = {}, {}
    for r in realset_runs:
        src = res.realset_source(sources, r["id"])

        def thumb_url(rel: str, _split=r["id"]) -> str:
            path = res.resolve_file(sources, _split, rel)
            return copier.thumb(path) if path else ""

        payload = res.realset_payload(sources, r["id"], thumb_url)
        if payload is None:
            continue
        realset_payloads[r["id"]] = payload
        for card in payload["items"]:
            for mode in card["modes"]:
                prefix = f"data/rs/{r['id']}/{card['image'][:16]}/{mode}"
                view = _with_files(
                    lambda url, _c=card, _m=mode, _s=r["id"]: res.realset_item_view(sources, _s, _c["image"], _m, url),
                    lambda rel, _src=src: (_src.root / rel) if (_src.root / rel).is_file() else None,
                    copier, prefix, texts)
                if view:
                    items[f"{r['id']}/{card['image']}/{mode}"] = view

    # Workbench examples: the bundled sample runs (demo), each mode
    runs, examples = {}, []
    if demo:
        index = demomod.load_index()
        samples = {s["id"]: s for s in demomod.load_samples()}
        for key, entry in index.get("runs", {}).items():
            run_dir = demo_dir() / entry["dir"]
            sample = samples.get(entry["sample"], {})
            run_id = f"sample-{entry['sample']}-{entry['mode']}"
            events = _strip_t(demomod.read_events(run_dir))
            record = {"id": run_id, "filename": sample.get("title", entry["sample"]), "sample_id": entry["sample"],
                      "notices": [("Real Grok output, dev set: the saved live run (grok-4.3), every model turn "
                                   "included." if entry["mode"] == "agent" else
                                   "Real Grok output, dev set: the saved live run, with the text check's answer "
                                   "from grok-4.3.")] if entry.get("real") else [],
                      "spec": {"product": "die_cut", "size_in": entry["size_in"], "prompt": None},
                      "mode": entry["mode"], "model": entry.get("model") if entry["mode"] == "agent" else None,
                      "vision": entry.get("vision"), "status": "done", "demo": True, "engine": "demo",
                      "real": bool(entry.get("real"))}
            original = demomod.sample_path(sample) if sample else samples_dir() / "missing"
            original_name = "original" + original.suffix  # the sample image, served next to the run's files

            def make(url, _d=run_dir, _r=record, _e=events, _o=original, _n=original_name):
                return build_view(_d, _r, url, _e, original=(_o, url(_n)))

            view = _with_files(make, lambda name, _d=run_dir, _o=original, _n=original_name: _o if name == _n else _d / name,
                               copier, f"data/runs/{run_id}", texts)
            if view is None:
                continue
            view["readonly"] = True
            runs[run_id] = view
            res_ = view.get("result") or {}
            examples.append({"id": run_id, "title": record["filename"], "filename": record["filename"],
                             "sample": entry["sample"], "real": bool(entry.get("real")),
                             "mode": entry["mode"], "size_in": entry["size_in"], "outcome": res_.get("outcome"),
                             "status": "done", "note": sample.get("note") or "demo sample",
                             "thumb": copier.thumb(original, 160) if original.exists() else None})

    examples.sort(key=lambda e: not e["real"])  # the real Grok examples lead (stable: sample order kept)
    state = {
        "version": webstate.version(), "mode": "app", "demo": demo, "static": True,
        "profile": webstate.profile_payload(), "models": webstate.models_payload(),
        "default_model": webstate.MODELS[0]["id"], "sizes": [2, 3, 4, 5], "size_limits": {"min": 0.5, "max": 20},
        "products": [{"id": "die_cut", "label": "Die-cut sticker"}], "samples": [], "labeller": "Ebin",
        "runner": {"engine": "static"}, "label": {"available": False},
        "results": {"bench_splits": [{"split": s, "demo": bool(b.get("demo"))} for s, b in bench_data.items()],
                    "realset_runs": [r for r in realset_runs if r["id"] in realset_payloads]},
    }
    data = {"state": state, "examples": examples, "runs": runs, "items": items, "bench": bench_data,
            "realsets": state["results"]["realset_runs"], "realset": realset_payloads, "texts": texts}

    # static files: CSS, favicon, the bundle, the data, and index.html wired to them
    for css in (STATIC_DIR / "css").glob("*.css"):
        shutil.copyfile(css, out / "static" / "css" / css.name)
    shutil.copyfile(STATIC_DIR / "favicon.svg", out / "static" / "favicon.svg")
    (out / "static" / "app.js").write_text(bundle_js(), encoding="utf-8")
    payload = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    (out / "static" / "data.js").write_text(f"window.PRINTREADY_STATIC = {payload};\n", encoding="utf-8")
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = re.sub(r"<!--printready:app-script-->.*?<!--/printready:app-script-->",
                  '<script src="static/data.js"></script>\n    <script src="static/app.js"></script>', html, flags=re.S)
    html = html.replace("<!--printready:static-data-->", '<meta name="robots" content="noindex" />')
    html = html.replace("<title>printready</title>", "<title>printready · read-only demo</title>")
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")  # GitHub Pages: serve files as they are

    total_files = sum(1 for p in out.rglob("*") if p.is_file())
    total_bytes = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    return {"files": total_files, "bytes": total_bytes, "items": len(items), "samples": len(runs),
            "bench": ", ".join(bench_data) or None}
