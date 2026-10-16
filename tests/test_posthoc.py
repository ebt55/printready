"""analysis/posthoc.py (post hoc, exploratory) on a small synthetic test split with known answers."""

import importlib.util
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from printready import realset

SPEC = importlib.util.spec_from_file_location("posthoc", Path(__file__).resolve().parents[1] / "analysis" / "posthoc.py")
posthoc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(posthoc)

IMAGES = [f"{i:064x}" for i in range(4)]
FIXED = [f"{0xF0 + i:064x}" for i in range(4)]
LABELS = ["ready_diecut", "fixable_diecut", "scene", "scene"]
PASS = {"text_garbled": {"status": "pass", "fixer": "none"}}
SKIP = {"text_garbled": {"status": "skip", "fixer": "none"}}


def png(seed: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (seed * 40 % 255, 10, 10)).save(buf, format="PNG")
    return buf.getvalue()


def row(root, where, i, outcome, shape="die_cut", reason=None, after=PASS, attempt=None, message="msg"):
    out_dir = f"results/realset/{where}/{IMAGES[i]}"
    (root / out_dir).mkdir(parents=True, exist_ok=True)
    (root / out_dir / "proof.png").write_bytes(png(i))
    r = {"image": IMAGES[i], "prompt_id": f"p{i:02d}", "image_model": "xai:grok-imagine-image", "outcome": outcome,
         "shape": shape, "handoff_reason": reason, "after": after, "fixed_sha256": FIXED[i], "out_dir": out_dir,
         "customer_message": f"{where} {message} {i}", "cost_usd": 0.0, "elapsed_s": 1.0}
    return r | ({"attempt": attempt} if attempt else {})


@pytest.fixture
def tree(tmp_path, monkeypatch):
    monkeypatch.setenv(realset.ROOT_ENV, str(tmp_path))
    paths = realset.Paths.for_split("test")
    realset.append_jsonl(paths.manifest, [{"sha256": s, "prompt_id": f"p{i:02d}", "prompt": "x", "model": "m",
                                           "file": f"images/{s}.jpg", "format": "JPEG"} for i, s in enumerate(IMAGES)])
    realset.append_jsonl(paths.labels, [{"ts": "t", "pass": 1, "image": s, "proof": None, "label": lab}
                                        for s, lab in zip(IMAGES, LABELS)])
    t = tmp_path
    realset.append_jsonl(paths.runs("rules"), [
        row(t, "test/rules", 0, "fixable"), row(t, "test/rules", 1, "fixable"),
        row(t, "test/rules", 2, "fixable", "rounded_rect"), row(t, "test/rules", 3, "needs_person", after=SKIP)])
    realset.append_jsonl(paths.runs("agent"), [row(t, "test/agent", i, "needs_person", reason="error") for i in range(4)])
    rr = posthoc.rerun_runs
    realset.append_jsonl(rr(paths, "rules"), [row(t, "test-rerun/rules", 3, "fixable", "rounded_rect", attempt=1)])
    realset.append_jsonl(rr(paths, "agent"), [
        row(t, "test-rerun/agent", 0, "fixable", attempt=1),
        row(t, "test-rerun/agent", 1, "needs_person", reason="garbled text", attempt=1),
        row(t, "test-rerun/agent", 2, "fixable", "rounded_rect", attempt=1),
        row(t, "test-rerun/agent", 3, "needs_person", reason="turn limit", attempt=2)])
    realset.append_jsonl(posthoc.rerun_root(paths) / "attempts.jsonl", [
        {"mode": "rules", "image": IMAGES[3], "attempt": 1, "billed": True},
        *[{"mode": "agent", "image": IMAGES[i], "attempt": 1, "billed": i != 3} for i in range(4)],
        {"mode": "agent", "image": IMAGES[3], "attempt": 2, "billed": True}])
    items = [{"image": IMAGES[i], "proof": FIXED[i], "file": f"label-images/{FIXED[i]}.png"} for i in range(4)]
    for i in range(4):
        (paths.data / "label-images").mkdir(exist_ok=True)
        (paths.data / items[i]["file"]).write_bytes(png(i))
    realset.write_json(paths.data / "label-pass2.json", {"pass": 2, "caption": "3 in die-cut sticker",
                                                         "keys": {"y": "acceptable", "n": "unacceptable"},
                                                         "labels": "labels.jsonl", "items": items})
    return paths


def test_all_integrity_checks_pass_and_the_report_is_marked_post_hoc(tree, capsys):
    assert posthoc.main([]) == 0
    out = capsys.readouterr().out
    assert out.count("PASS") == 3 and "FAIL" not in out
    md = (tree.results / "posthoc.md").read_text(encoding="utf-8")
    assert md.count("(post hoc)") >= 7 and "Post hoc, exploratory" in md
    assert "no mode can agree on more than **3 of 4**" in md  # one image Ebin called ready as a die-cut


def test_a_billed_attempt_without_a_row_fails(tree):
    realset.append_jsonl(posthoc.rerun_root(tree) / "attempts.jsonl",
                         [{"mode": "rules", "image": IMAGES[0], "attempt": 1, "billed": True}])
    ok, msg = posthoc.check_attempts(posthoc.Data(tree))
    assert not ok and "1 without a runs.jsonl row" in msg
    assert posthoc.main([]) == 1


def test_different_proofs_for_one_fixed_png_fail(tree):
    rerun_proof = tree.root / "results/realset/test-rerun/agent" / IMAGES[0] / "proof.png"
    assert posthoc.check_proofs(posthoc.Data(tree))[0]  # rules and agent share FIXED[0] and its proof bytes
    rerun_proof.write_bytes(png(9))
    ok, msg = posthoc.check_proofs(posthoc.Data(tree))
    assert not ok and FIXED[0][:12] in msg


@pytest.mark.parametrize("change", [
    lambda page: page["items"][0].update(mode="agent"),
    lambda page: page["items"][0].update(file=f"label-images/rules-{FIXED[0]}.png"),
    lambda page: page.update(source="rerun"),
])
def test_a_pass_2_list_that_leaks_mode_or_source_fails(tree, change):
    path = tree.data / "label-pass2.json"
    page = json.loads(path.read_text())
    change(page)
    path.write_text(json.dumps(page))
    assert not posthoc.check_pass2_blind(posthoc.Data(tree))[0]


def test_a_missing_pass_2_list_fails(tree):
    (tree.data / "label-pass2.json").unlink()
    ok, msg = posthoc.check_pass2_blind(posthoc.Data(tree))
    assert not ok and "--build-pass2" in msg


def test_views_original_and_with_reruns(tree):
    d = posthoc.Data(tree)
    original, rerun = d.views["original runs"], d.views["with reruns"]
    assert {m: v["agree"] for m, v in posthoc.product_view(d, original).items()} == {"rules": 3, "agent": 0}
    pv = posthoc.product_view(d, rerun)
    assert pv["rules"]["agree"] == 4 and pv["agent"]["agree"] == 2
    assert pv["agent"]["matrix"]["rounded_rect"] == {"die_cut": 0, "rounded_rect": 1, "needs_person": 1}
    tc = posthoc.two_class_view(d, rerun)
    assert tc["agent"] == {"prereg (scene = no person)": 2, "scene = person": 2, "n": 4}
    assert tc["rules"] == {"prereg (scene = no person)": 4, "scene = person": 2, "n": 4}
    assert posthoc.handoffs(d, original) == {"rules": {"error": 1}, "agent": {"error": 4}}
    assert posthoc.handoffs(d, rerun) == {"rules": {}, "agent": {"model choice": 1, "turn limit": 1}}
    c = posthoc.ceiling(d)
    assert (c["ceiling"], c["opaque_jpeg"], c["ready_outputs"]) == (3, 4, 0)


def test_customer_messages_are_picked_by_seed_from_both_modes(tree):
    d = posthoc.Data(tree)
    picks = posthoc.messages(d, d.views["with reruns"])
    assert picks == posthoc.messages(d, d.views["with reruns"])  # deterministic
    assert {p["image"] for p in picks} == {IMAGES[0], IMAGES[2]}  # the only images both modes would send
    assert picks[0]["rules"].startswith("test/rules") and picks[0]["agent"].startswith("test-rerun/agent")
