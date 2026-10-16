"""Bench runner and report: the IoU helper and the metrics on synthetic predictions (no detectors),
then one end-to-end `bench run` + `bench report` on the tiny generated split."""

import json

import numpy as np

from printready.bench.labels import Thresholds
from printready.bench.report import disagreements, fix_success, summarize
from printready.bench.run import band_iou, place
from printready.cli import main
from printready.profile import load_profile
from printready.types import DETERMINISTIC_CHECK_IDS


def _disc(h, w, cx, cy, r):
    yy, xx = np.mgrid[0:h, 0:w]
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r


def test_band_iou_ignores_the_edge_band_only():
    gt = _disc(80, 80, 40, 40, 25)
    assert band_iou(gt, gt) == 1.0
    grown = _disc(80, 80, 40, 40, 26)  # one pixel fatter: inside the 2 px band, so no penalty
    assert band_iou(grown, gt) == 1.0
    halved = gt & (np.arange(80)[None, :] < 40)  # half the subject missing: a real loss
    assert band_iou(halved, gt) < 0.6


def test_place_applies_the_pad_offset():
    gt = np.zeros((10, 10), bool)
    gt[2:4, 3:5] = True
    moved = place(gt, (14, 16), (5, 3))  # original (x, y) is now (x + 5, y + 3)
    assert moved.shape == (14, 16)
    assert np.array_equal(np.argwhere(moved), np.argwhere(gt) + [3, 5])


def _perfect(rows):
    """Predictions that agree with every label, as predictions.jsonl would hold them."""
    preds = {}
    for row in rows:
        before = {c: dict(row["expected"][c], measured={}) for c in DETERMINISTIC_CHECK_IDS}
        after = {c: {"status": s, "fixer": "none"} for c, s in row["expected_final"].items()}
        preds[row["id"]] = {"id": row["id"], "errors": [], "before": before, "after": after,
                            "outcome": row["outcome"], "steps": [], "iou": 1.0, "offset": [0, 0],
                            "pipeline_before_agrees": True}
    return preds


def test_metrics_on_synthetic_predictions(generated):
    _, _, rows = generated
    th = Thresholds.from_profile(load_profile())
    preds = _perfect(rows)
    s = summarize(rows, preds, th, None, "dev")
    assert s["disagreements"] == [] and s["outcome"]["accuracy"] == 1.0
    assert s["fix_success"]["rate"] == 1.0
    for check, m in s["checks"].items():
        assert sum(map(sum, m["matrix"]["counts"])) == len(rows)
        assert m["recall"] in (None, 1.0) and m["clean_false_flag"] == 0.0
    # One missed defect and one damaged fix show up where they should.
    edge = next(r for r in rows if r["family"] == "edge_crop")
    preds[edge["id"]]["before"]["edge_crop"] = {"status": "pass", "fixer": "none", "measured": {"run_in": 0}}
    preds[edge["id"]]["steps"] = [{"fix": "pad_canvas", "ok": True, "damaged": True, "guard": {}}]
    dis = disagreements(rows, preds, th)
    assert [(d["id"], d["check"], d["expected"], d["predicted"]) for d in dis] == [
        (edge["id"], "edge_crop", "warn/auto", "pass")]
    assert "longest edge run" in dis[0]["ground_truth"]
    fx = fix_success(rows, preds)
    assert [r["id"] for r in fx["rows"] if not r["ok"]] == [edge["id"]]


def test_run_and_report_end_to_end(generated):
    root, manifest, rows = generated
    common = ["--split", "dev", "--limit", "1", "--root", str(root), "--manifest", str(manifest)]
    assert main(["bench", "run", *common, "--jobs", "1"]) == 0
    assert main(["bench", "report", *common]) == 0
    out = root / "results" / "bench" / "dev" / "limit1"
    preds = [json.loads(line) for line in (out / "predictions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [p["id"] for p in preds] == [r["id"] for r in rows]
    for p in preds:
        assert p["errors"] == [], p["id"]
        assert set(p["before"]) >= set(DETERMINISTIC_CHECK_IDS) and set(p["after"]) >= set(DETERMINISTIC_CHECK_IDS)
        assert p["outcome"] in ("ready", "fixable", "needs_person")
        assert p["iou"] is None or 0.0 <= p["iou"] <= 1.0
    opaque = next(p for p in preds if p["family"] == "background")
    assert opaque["iou"] is not None  # removal ran (white background), so the subject was scored
    assert not (out / "summary.json").exists()
    summary = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert summary["n"] == len(rows) and set(summary["checks"]) == set(DETERMINISTIC_CHECK_IDS)
    for m in summary["checks"].values():
        assert {"n", "matrix", "recall", "clean_false_flag", "fixer_agreement"} <= set(m)
        assert {"rows", "cols", "counts"} == set(m["matrix"])
    assert sum(h["count"] for h in summary["heat"]) == len(rows) * len(DETERMINISTIC_CHECK_IDS)
    text = (out / "report.md").read_text(encoding="utf-8")
    for heading in ("## Headline", "## Confusion matrices", "## Fix success", "## Outcome", "## Disagreements"):
        assert heading in text
    assert (out / "confusion.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_run_and_report_refuse_without_data(tmp_path, capsys):
    assert main(["bench", "run", "--split", "dev", "--root", str(tmp_path)]) == 1
    assert main(["bench", "report", "--split", "dev", "--root", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "bench generate" in err and "bench run" in err


def test_vision_run_offline_with_the_fake_provider(generated, tmp_path, monkeypatch):
    """--vision through the public vision API with scripted answers: estimate, dry run, then a run
    that scores one garbled reading against the planted label."""
    root, manifest, rows = generated
    text_row = next(r for r in rows if r["family"] == "text")
    answer = {"text": [{"seen": "XYZ", "intended": text_row["param"]["intended"], "broken": False,
                        "box": [0.2, 0.4, 0.8, 0.6]}], "notes": ""}  # the vision prompt's answer schema
    script = tmp_path / "fake.json"
    script.write_text(json.dumps([{"text": json.dumps(answer), "usage": {"in": 700, "out": 200}}]), encoding="utf-8")
    monkeypatch.setenv("PRINTREADY_SPEND_LEDGER", str(tmp_path / "ledger.jsonl"))
    common = ["bench", "run", "--split", "dev", "--limit", "1", "--root", str(root), "--manifest", str(manifest),
              "--vision", "--model", f"fake:{script}"]
    out = root / "results" / "bench" / "dev" / "limit1"
    assert main(common) == 0 and not (out / "vision.jsonl").exists()  # dry run: estimate only
    assert main([*common, "--yes"]) == 0
    vision = [json.loads(line) for line in (out / "vision.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [v["id"] for v in vision] == [text_row["id"]]
    assert vision[0]["findings"]["text_garbled"]["status"] == "fail"
    assert main(["bench", "report", "--split", "dev", "--limit", "1", "--root", str(root),
                 "--manifest", str(manifest)]) == 0
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    garbled = metrics["vision"]["text_garbled"]
    assert garbled["n"] == 1 and garbled["fp"] == 1  # the planted word is spelled right, the fake says garbled
    assert metrics["vision"]["disagreements"][0]["check"] == "text_garbled"
    assert "## Vision" in (out / "report.md").read_text(encoding="utf-8")
