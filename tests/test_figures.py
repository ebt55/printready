"""README figures from a tiny fake results tree (offline, no real images or runs needed)."""

import json

import numpy as np
import pytest
from PIL import Image

from printready import figures
from printready.cli import main

CHECKS = ("file", "resolution", "background", "soft_alpha", "edge_crop", "islands")


def _finding(check, status="pass", fixer="none", **measured):
    return {"check": check, "status": status, "fixer": fixer, "message": "", "measured": measured, "boxes": []}


def _image(path, colour):
    arr = np.full((120, 120, 3), 244, np.uint8)
    arr[30:90, 30:90] = colour
    Image.fromarray(arr).save(path)


def _write_run(root, sha, prompt_id, model, outcome, fixed):
    out_dir = root / "results" / "realset" / "dev" / "rules" / sha
    out_dir.mkdir(parents=True)
    before = [_finding(c) for c in CHECKS]
    before[1]["measured"] = {"ppi": 366.0}
    before[2] = _finding("background", "fail", "auto" if fixed else "person", colour_hex="#f4f4f4")
    history = ([{"fix": "remove_background", "ok": True, "damaged": False}, {"fix": "add_border", "ok": True,
                                                                             "damaged": False}] if fixed else [])
    after = [_finding(c) for c in CHECKS] if fixed else before
    report = {"mode": "rules", "outcome": outcome, "handoff_reason": None, "art": {"offset": [0, 0]},
              "history": history, "before": {"findings": before}, "after": {"findings": after}}
    (out_dir / "report.json").write_text(json.dumps(report), encoding="utf-8")
    alpha = np.zeros((120, 120), np.uint8)
    alpha[26:94, 26:94] = 255
    rgba = np.dstack([np.full((120, 120, 3), 200, np.uint8), alpha])
    Image.fromarray(rgba).save(out_dir / "fixed.png")
    Image.new("RGB", (120, 140), "white").save(out_dir / "proof.png")
    (out_dir / "cutline.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1.2 1.2">'
        '<path d="M 0.26 0.26 L 0.94 0.26 L 0.94 0.94 L 0.26 0.94 Z" stroke="#e4007c"/></svg>', encoding="utf-8")
    return {"image": sha, "prompt_id": prompt_id, "image_model": model, "mode": "rules", "outcome": outcome,
            "steps": [h["fix"] for h in history], "out_dir": f"results/realset/dev/rules/{sha}"}


@pytest.fixture
def root(tmp_path):
    data = tmp_path / "data" / "realset" / "dev"
    (data / "images").mkdir(parents=True)
    runs, manifest = [], []
    specs = [("a" * 64, "d01", "xai:grok-imagine-image", "fixable", True),
             ("b" * 64, "d02", "xai:grok-imagine-image-2.0", "needs_person", False),
             ("c" * 64, "d03", "xai:grok-imagine-image", "fixable", True)]
    for sha, pid, model, outcome, fixed in specs:
        _image(data / "images" / f"{sha}.png", (200, 60, 40))
        manifest.append({"sha256": sha, "prompt_id": pid, "prompt": f"a sticker for {pid}", "model": model,
                         "file": f"images/{sha}.png"})
        runs.append(_write_run(tmp_path, sha, pid, model, outcome, fixed))
    (data / "manifest.jsonl").write_text("".join(json.dumps(m) + "\n" for m in manifest), encoding="utf-8")
    (tmp_path / "results/realset/dev/rules/runs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in runs),
                                                                    encoding="utf-8")
    matrix = {"rows": ["pass", "fail"], "cols": ["pass", "warn", "fail", "skip"], "counts": [[10, 0, 0, 0], [1, 0, 3, 0]]}
    metrics = {"split": "dev", "n": 14, "checks": {c: {"matrix": matrix, "n_expected_flagged": 4, "recall": 0.75,
                                                       "clean_false_flags": {"n": 10, "flagged": 0},
                                                       "fixer_agreement": 1.0, "fixer_pairs": {"n": 3, "agree": 3}}
                                                   for c in CHECKS},
               "vision": {"model": "xai:grok-4.3", "cost_usd": 0.1,
                          "text_garbled": {"precision": 1.0, "recall": 0.5, "tp": 1, "fp": 0, "fn": 1, "tn": 2}}}
    (tmp_path / "results/bench/dev").mkdir(parents=True)
    (tmp_path / "results/bench/dev/metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    return tmp_path


def test_cli_builds_all_four_figures(root, tmp_path):
    out = tmp_path / "img"
    assert main(["figures", "--root", str(root), "-o", str(out), "--hero", "aaaaaa",
                 "--gallery", "d01/grok-imagine-image", "bbbbbb", "cccccc"]) == 0
    for name in ("hero.png", "gallery-strip.png", "outcomes.png", "bench-heat.png"):
        with Image.open(out / name) as im:
            assert im.width == figures.WIDTH and im.height > 300, name


def test_resolve_and_defaults(root):
    images = figures.realset_runs(root, "dev")
    assert figures.resolve(images, "bbbbbbbb").prompt_id == "d02"
    assert figures.resolve(images, "d03/grok-imagine-image").sha == "c" * 64
    with pytest.raises(KeyError):
        figures.resolve(images, "abc")  # too short to be an id
    assert figures.default_hero(images).prompt_id == "d01"
    assert [im.prompt_id for im in figures.default_gallery(images)] == ["d01", "d02", "d03"]


def test_cut_path_is_read_in_fixed_image_pixels(root):
    paths = figures.cut_paths(root / "results/realset/dev/rules" / ("a" * 64))
    assert len(paths) == 1 and paths[0][0] == pytest.approx((26.0, 26.0)) and paths[0][-1] == paths[0][0]


def test_short_labels():
    assert figures.short_label(_finding("resolution", "pass", ppi=142.3), 3.0) == "142 PPI at 3 in"
    assert figures.short_label(_finding("background", "fail", "auto", colour_hex="#ffffff"), 3) == \
        "solid #ffffff background"
    assert figures.short_label(_finding("edge_crop", "fail", "person"), 3) == "art cut off at the edge"
    assert figures.short_label(_finding("islands", "pass"), 3) is None
    garbled = _finding("text_garbled", "fail", "person", items=[{"seen": "STIKCER", "garbled": True}])
    assert figures.short_label(garbled, 3) == 'garbled text "STIKCER"'
