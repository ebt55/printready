"""Real-set tooling, offline: fake image and chat clients, tiny images, a temporary repo tree."""

import base64
import io
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from printready import prereg, realset, spend
from printready.cli import main
from printready.llm import ChatClient, FakeTransport
from printready.realset import Paths, read_jsonl, sample_shas
from printready.realset import evaluate as ev
from printready.realset import gen, label, runs, sheet
from printready.spend import BudgetExceeded, Price

REPO = Path(__file__).resolve().parents[1]
MODELS = ["xai:grok-imagine-image", "xai:grok-imagine-image-2.0"]


@pytest.fixture
def prereg_ok(monkeypatch):
    monkeypatch.setattr(prereg, "require_verified", lambda root=None: None)


@pytest.fixture
def tree(tmp_path, monkeypatch):
    (tmp_path / "realset").mkdir()
    (tmp_path / "realset" / "prompts-dev.txt").write_text(
        '# model-drafted\na cute cat\n\na badge that says "SHOP"\na dog\n', encoding="utf-8")
    (tmp_path / "realset" / "prompts.txt").write_text(
        "\n".join(f"prompt {i}" for i in range(1, 13)) + "\n", encoding="utf-8")
    monkeypatch.setenv(realset.ROOT_ENV, str(tmp_path))
    return tmp_path


def png(seed: int) -> bytes:
    """An opaque 240 px sticker-like image: a coloured disc on white (distinct per seed)."""
    img = np.full((240, 240, 3), 255, np.uint8)
    cv2.circle(img, (120, 120), 70 + seed % 20, (40 + 9 * seed % 200, 90, 160), -1)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="PNG")
    return buf.getvalue()


def image_factory(fail: set[str] = frozenset(), calls: list | None = None):
    def factory(model):
        offset = MODELS.index(model) * 50 if model in MODELS else 0
        responses = [{"status": 400, "body": "blocked"} if f"{model}#{i}" in fail else
                     {"b64_json": base64.b64encode(png(offset + i)).decode(), "revised_prompt": f"revised {i}"}
                     for i in range(1, 60)]
        client = ChatClient(model, FakeTransport(responses), price=Price(per_image=0.02))
        if calls is not None:
            calls.append(client)
        return client
    return factory


def generated(split="dev"):
    paths = Paths.for_split(split)
    gen.generate(paths, MODELS, client_factory=image_factory(), log=lambda s: None)
    return paths


# ---------------------------------------------------------------- prompts

def test_committed_prompt_files_have_the_planned_shape():
    dev = realset.load_prompts(REPO / "realset" / "prompts-dev.txt", "d")
    test = realset.load_prompts(REPO / "realset" / "prompts.txt", "p")
    assert len(dev) == 10 and sum('"' in p for _, p in dev) == 5
    assert len(test) == 50 and sum('"' in p for _, p in test) == 25
    assert dev[0][0] == "d01" and test[-1][0] == "p50"
    assert not {p for _, p in dev} & {p for _, p in test}  # dev images are never test images
    assert "model-drafted" in (REPO / "realset" / "prompts.txt").read_text(encoding="utf-8").lower()


# ---------------------------------------------------------------- gen

def test_gen_stores_by_hash_writes_the_manifest_and_spends_through_the_ledger(tree):
    paths = generated()
    manifest = read_jsonl(paths.manifest)
    assert len(manifest) == 6 and {e["model"] for e in manifest} == set(MODELS)
    e = manifest[0]
    assert e["prompt_id"] == "d01" and e["prompt"] == "a cute cat" and e["revised_prompt"] == "revised 1"
    assert e["file"] == f"images/{e['sha256']}.png" and (paths.data / e["file"]).exists()
    assert (e["width"], e["height"], e["format"], e["cost_usd"]) == (240, 240, "PNG", 0.02)
    assert spend.ledger_total() == pytest.approx(0.12)
    assert "grok" not in e["file"]  # the file name never names the model


def test_gen_is_resumable_and_leaves_failures_for_later(tree):
    paths = Paths.for_split("dev")
    calls = []
    gen.generate(paths, MODELS, client_factory=image_factory(fail={"xai:grok-imagine-image#2"}, calls=calls),
                 log=lambda s: None)
    assert len(read_jsonl(paths.manifest)) == 5
    calls.clear()
    new = gen.generate(paths, MODELS, client_factory=image_factory(calls=calls), log=lambda s: None)
    assert [(e["prompt_id"], e["model"]) for e in new] == [("d02", "xai:grok-imagine-image")]
    assert len(calls) == 1 and len(calls[0].transport.requests) == 1  # only the missing one is asked for


def test_gen_stops_at_the_spend_cap(tree, monkeypatch):
    monkeypatch.setenv(spend.CAP_ENV, "0.05")
    with pytest.raises(BudgetExceeded):
        gen.generate(Paths.for_split("dev"), MODELS, client_factory=image_factory(), log=lambda s: None)
    assert len(read_jsonl(Paths.for_split("dev").manifest)) == 2  # $0.04 spent, the third would pass $0.05


@pytest.mark.parametrize("action", [["gen", "--split", "test"], ["run", "--split", "test", "--mode", "rules"]])
def test_test_split_needs_a_verified_prereg(tree, monkeypatch, capsys, action):
    def refuse(root=None):
        raise prereg.PreregError("preregistration check failed:\n  PREREG.md is not committed")

    monkeypatch.setattr(prereg, "require_verified", refuse)
    assert main(["realset", *action]) == 1
    assert "PREREG.md is not committed" in capsys.readouterr().err
    assert not Paths.for_split("test").manifest.exists()


# ---------------------------------------------------------------- run

def test_rules_run_writes_outputs_and_one_summary_per_image(tree):
    paths = generated()
    rows = runs.run_split(paths, "rules", runs.select(paths, sample=False), log=lambda s: None)
    assert len(rows) == 6
    row = rows[0]
    assert row["mode"] == "rules" and row["outcome"] in ("ready", "fixable", "needs_person")
    assert row["shape"] == "die_cut"
    assert row["before"]["background"] == {"status": "fail", "fixer": "auto"}
    assert row["steps"][0] == {"fix": "remove_background", "ok": True, "damaged": False}
    assert row["fixed_sha256"] and (paths.root / row["out_dir"] / "proof.png").exists()
    assert row["out_dir"] == f"results/realset/dev/rules/{row['image']}"
    assert runs.run_split(paths, "rules", runs.select(paths, sample=False), log=lambda s: None) == []  # resumable
    again = runs.run_split(paths, "rules", runs.select(paths, sample=False)[:1], force=True, log=lambda s: None)
    assert len(again) == 1 and len(read_jsonl(paths.runs("rules"))) == 7  # the last line per image wins


def agent_factory(clients):
    def factory():
        script = [{"tool_calls": [{"name": "handoff", "arguments": {"reason": "test", "person_notes": "n"}}]}]
        client = ChatClient("fake:agent", FakeTransport(script), price=Price())
        clients.append(client)
        return client
    return factory


def test_agent_run_needs_a_client_and_never_reruns_on_test(tree):
    paths = generated("test")
    items = runs.select(paths, sample=False)[:2]
    with pytest.raises(ValueError, match="needs a model client"):
        runs.run_split(paths, "agent", items, log=lambda s: None)
    clients = []
    rows = runs.run_split(paths, "agent", items, client_factory=agent_factory(clients), log=lambda s: None)
    assert [r["handoff_reason"] for r in rows] == ["test", "test"] and len(clients) == 2  # one client per image
    assert (paths.root / rows[0]["out_dir"] / "log.jsonl").exists()
    assert runs.run_split(paths, "agent", items, client_factory=agent_factory(clients), force=True,
                          log=lambda s: None) == []  # PREREG 5: one agent run per test image
    assert len(clients) == 2


def test_dev_agent_runs_may_be_repeated_for_tuning(tree):
    paths = generated("dev")
    items = runs.select(paths, sample=False, only=["d02"])
    assert [e["prompt_id"] for e in items] == ["d02", "d02"]  # both image models
    assert runs.select(paths, sample=False, only=[items[0]["sha256"][:8]]) == items[:1]
    clients = []
    runs.run_split(paths, "agent", items, client_factory=agent_factory(clients), log=lambda s: None)
    again = runs.run_split(paths, "agent", items, client_factory=agent_factory(clients), force=True, log=lambda s: None)
    assert len(again) == 2 and len(clients) == 4


def test_rules_mode_runs_the_vision_check_when_given_a_client(tree):
    paths = generated()
    answer = {"text": json.dumps({"text": [{"seen": "SHOP", "intended": "SHOP", "broken": False,
                                            "box": None}], "notes": ""})}
    clients = []

    def vision_factory():
        clients.append(ChatClient("fake:vision", FakeTransport([answer]), price=Price()))
        return clients[-1]

    (row,) = runs.run_split(paths, "rules", runs.select(paths, sample=False)[:1], client_factory=vision_factory,
                            log=lambda s: None)
    assert row["after"]["text_garbled"] == {"status": "pass", "fixer": "none"} and row["model"] == "fake:vision"
    assert len(clients[0].transport.requests) == 1


def test_agent_cli_shows_the_estimate_and_needs_yes(tree, monkeypatch, capsys):
    generated()
    monkeypatch.setenv("XAI_API_KEY", "xai-test-not-real")
    (tree / "empty.env").write_text("", encoding="utf-8")
    assert main(["realset", "run", "--split", "dev", "--mode", "agent", "--env-file", str(tree / "empty.env")]) == 2
    out = capsys.readouterr()
    assert "agent mode on 6 images with xai:grok-4.3: about $0.06, at most $" in out.out
    assert "--yes" in out.err
    assert not Paths.for_split("dev").runs("agent").exists()


def test_test_split_runs_wait_for_pass_1_labels(tree, prereg_ok, capsys):
    paths = generated("test")
    assert main(["realset", "run", "--split", "test", "--mode", "rules"]) == 2
    assert "need a pass-1 label" in capsys.readouterr().err
    realset.append_jsonl(paths.labels, [{"ts": "t", "pass": 1, "image": s, "proof": None, "label": "fixable_diecut"}
                                        for s in sample_shas(read_jsonl(paths.manifest))])
    assert main(["realset", "run", "--split", "test", "--mode", "rules", "--limit", "1"]) == 0


def test_sample_is_seeded_and_model_blind():
    manifest = [{"sha256": f"{i:064x}"} for i in range(100)]
    a, b = sample_shas(manifest), sample_shas(list(reversed(manifest)))
    assert a == b and len(a) == 50 and len(set(a)) == 50
    assert sample_shas(manifest[:20]) == sorted(e["sha256"] for e in manifest[:20])


# ---------------------------------------------------------------- label

def test_pass1_items_are_blind_png_copies_by_hash(tree):
    paths = generated()
    data = label.pass1_items(paths)
    assert data["pass"] == 1 and data["caption"] == "3 in die-cut sticker"
    assert data["keys"] == {"1": "ready_diecut", "2": "fixable_diecut", "3": "scene", "4": "needs_person"}
    assert len(data["items"]) == 6 and [i["image"] for i in data["items"]] != sorted(i["image"] for i in data["items"])
    for item in data["items"]:
        assert item["file"] == f"label-images/{item['image']}.png" and (paths.data / item["file"]).exists()
    assert json.loads((paths.data / "label-pass1.json").read_text()) == data
    assert "grok" not in json.dumps(data)


def test_pass2_dedupes_identical_proofs_across_modes_and_keeps_the_mapping_apart(tree):
    paths = generated()
    rules_rows = runs.run_split(paths, "rules", runs.select(paths, sample=False), log=lambda s: None)
    sendable = [r for r in rules_rows if r["outcome"] != "needs_person"]
    assert sendable, "the fake images should give some proofs a customer would see"
    # agent rows that produced the very same fixed.png as rules on two images, plus one handoff
    agent_rows = [{**r, "mode": "agent"} for r in sendable[:2]] + [{**rules_rows[-1], "mode": "agent", "outcome": "needs_person"}]
    realset.append_jsonl(paths.runs("agent"), agent_rows)
    data = label.pass2_items(paths)
    proofs = [i["proof"] for i in data["items"]]
    assert len(proofs) == len(set(proofs)) == len({r["fixed_sha256"] for r in sendable})
    assert all((paths.data / i["file"]).exists() and i["file"].startswith("label-images/") for i in data["items"])
    assert "rules" not in json.dumps(data) and "agent" not in json.dumps(data)
    mapping = json.loads((paths.data / "label-pass2-mapping.json").read_text())
    shared = sendable[0]["fixed_sha256"]
    assert sorted(m["mode"] for m in mapping[shared]) == ["agent", "rules"]


def test_serve_labels_calls_the_workbench_or_explains(tree):
    paths = generated()
    calls = []

    class WithServe:
        @staticmethod
        def serve(label_dir, label_pass, open_browser=True, port=8765):
            calls.append((label_dir, label_pass, open_browser))

    assert label.serve_labels(paths, 1, open_browser=False, server=WithServe) == 0
    assert calls == [(paths.data, 1, False)]
    said = []
    assert label.serve_labels(paths, 1, server=object(), log=said.append) == 2
    assert "not there yet" in said[0]


# ---------------------------------------------------------------- eval

def synthetic(paths, n=10, rules_right=4, agent_right=9, unacceptable_agent=0, damaged_rules=0,
              label="fixable_diecut", shape="die_cut"):
    """n labelled images, all with `label`; each mode says fixable on its first k images."""
    manifest = [{"prompt_id": f"p{i:02d}", "prompt": "x", "model": MODELS[i % 2], "sha256": f"{i:064x}",
                 "file": f"images/{i:064x}.png"} for i in range(n)]
    realset.append_jsonl(paths.manifest, manifest)
    realset.append_jsonl(paths.labels, [{"ts": "t", "pass": 1, "image": e["sha256"], "proof": None, "label": label}
                                        for e in manifest])
    mapping = {}
    for mode, right in (("rules", rules_right), ("agent", agent_right)):
        rows = []
        for i, e in enumerate(manifest):
            outcome = "fixable" if i < right else "needs_person"
            proof = f"{mode}-{i}" if outcome == "fixable" else None
            rows.append({"image": e["sha256"], "prompt_id": e["prompt_id"], "image_model": e["model"], "mode": mode,
                         "outcome": outcome, "shape": shape if outcome == "fixable" else "die_cut",
                         "handoff_reason": None, "fixed_sha256": proof, "out_dir": "x",
                         "damaged": mode == "rules" and i < damaged_rules, "cost_usd": 0.01 if mode == "agent" else 0,
                         "elapsed_s": 1.0})
            if proof:
                mapping[proof] = [{"mode": mode, "image": e["sha256"]}]
                bad = mode == "agent" and i < unacceptable_agent
                realset.append_jsonl(paths.labels, [{"ts": "t", "pass": 2, "image": e["sha256"], "proof": proof,
                                                     "label": "unacceptable" if bad else "acceptable"}])
        realset.append_jsonl(paths.runs(mode), rows)
    realset.write_json(paths.data / "label-pass2-mapping.json", mapping)


def test_eval_keeps_the_agent_only_past_the_margin(tree):
    paths = Paths.for_split("test")
    synthetic(paths, rules_right=4, agent_right=9)
    s = ev.evaluate(paths)
    assert s["modes"]["rules"]["agree"] == 4 and s["modes"]["agent"]["agree"] == 9
    assert s["modes"]["agent"]["matrix"]["fixable_diecut"] == {"ready": 0, "fixable": 9, "needs_person": 1}
    assert s["paired"] == {"n": 10, "both_agree": 4, "only_rules_agrees": 0, "only_agent_agrees": 5, "neither": 1}
    assert s["verdict"]["status"] == "keep_agent" and s["verdict"]["agent_minus_rules"] == 5
    assert s["rules_by_image_model"][MODELS[0]] == {"ready": 0, "fixable": 2, "needs_person": 3}
    assert s["modes"]["agent"]["cost_usd"]["total"] == pytest.approx(0.1)
    assert (paths.results / "eval.md").read_text().startswith("# Real set (test)")
    assert json.loads((paths.results / "summary.json").read_text())["verdict"]["status"] == "keep_agent"
    assert {c["image"] for c in s["images"]} == {f"{i:064x}" for i in range(10)}


def test_eval_margin_of_four_or_more_bad_fixes_keeps_rules(tree):
    paths = Paths.for_split("test")
    synthetic(paths, rules_right=5, agent_right=9)
    assert ev.evaluate(paths)["verdict"]["status"] == "keep_rules"


def test_eval_bad_fixes_count_against_the_agent(tree):
    paths = Paths.for_split("test")
    synthetic(paths, rules_right=3, agent_right=9, unacceptable_agent=2, damaged_rules=1)
    s = ev.evaluate(paths)
    assert s["modes"]["agent"]["bad_fixes"] == 2 and s["modes"]["rules"]["bad_fixes"] == 1
    assert s["verdict"]["status"] == "keep_rules"


def test_eval_scenes_count_as_fixable_and_are_also_reported_as_needs_person(tree):
    paths = Paths.for_split("test")
    synthetic(paths, rules_right=8, agent_right=3, unacceptable_agent=1, label="scene", shape="rounded_rect")
    s = ev.evaluate(paths)
    rules, agent = s["modes"]["rules"], s["modes"]["agent"]
    assert (rules["agree"], rules["agree_scene_as_person"]) == (8, 2)  # policy moves the number a lot
    assert (agent["agree"], agent["agree_scene_as_person"]) == (3, 7)
    assert s["sample"]["scenes"] == 10 and s["labels"]["pass1"] == {"scene": 10}
    assert (rules["scene_shaped_proofs"], rules["scene_shaped_accepted"]) == (8, 8)
    assert (agent["scene_shaped_proofs"], agent["scene_shaped_accepted"], agent["unacceptable"]) == (3, 2, 1)
    md = (paths.results / "eval.md").read_text()
    assert "10 scenes; shaped-sticker proofs accepted: rules 8 of 8; agent 2 of 3." in md
    assert s["images"][0]["rules"]["shape"] == "rounded_rect"


def test_eval_is_pending_until_everything_is_labelled(tree):
    paths = Paths.for_split("test")
    realset.append_jsonl(paths.manifest, [{"prompt_id": "p01", "prompt": "x", "model": MODELS[0],
                                           "sha256": "a" * 64, "file": "images/a.png"}])
    s = ev.evaluate(paths)
    assert s["verdict"]["status"] == "pending" and "pass-1 labels 0/1" in s["verdict"]["reason"]


# ---------------------------------------------------------------- contact sheet

def test_contact_sheet(tree):
    paths = generated()
    runs.run_split(paths, "rules", runs.select(paths, sample=False), log=lambda s: None)
    out = sheet.contact_sheet(paths, "rules")
    assert out == paths.results / "contact-sheet.png"
    with Image.open(out) as im:
        assert im.width == 2 * (2 * sheet.THUMB + sheet.TEXT_W + 4 * sheet.PAD) and im.height > 3 * sheet.THUMB
    row = read_jsonl(paths.runs("rules"))[0]
    assert any(line.startswith("background: fail -> pass") for line in sheet.flagged_lines(row))


def test_the_spend_cap_stops_a_batch_without_recording_a_budget_outcome(tree, monkeypatch):
    paths = generated()
    spend.record("xai", "x", 0, 0, 0, 0, 9.99, "earlier")
    with pytest.raises(BudgetExceeded):
        runs.run_split(paths, "agent", runs.select(paths, sample=False), client_factory=agent_factory([]),
                       log=lambda s: None)
    assert not paths.runs("agent").exists()  # nothing recorded: the images can run once the cap allows

    monkeypatch.setenv(spend.CAP_ENV, "20")
    budget_script = [{"status": 200}]  # unused: the run below ends in a budget handoff instead

    def budget_run(*a, **kw):
        from printready.types import Report, RunResult
        return RunResult(mode="agent", art=None, before=Report([]), after=Report([]), outcome="needs_person",
                         customer_message="", handoff_reason="budget")

    monkeypatch.setattr(runs, "run_agent", budget_run)
    with pytest.raises(BudgetExceeded, match="not recorded"):
        runs.run_split(paths, "agent", runs.select(paths, sample=False)[:1], client_factory=agent_factory([]),
                       log=lambda s: None)
    assert not paths.runs("agent").exists() and budget_script


def test_compare_sheet_marks_disagreements(tree):
    paths = generated()
    rules_rows = runs.run_split(paths, "rules", runs.select(paths, sample=False), log=lambda s: None)
    runs.run_split(paths, "agent", runs.select(paths, sample=False)[:3], client_factory=agent_factory([]),
                   log=lambda s: None)
    out = sheet.compare_sheet(paths)
    assert out == paths.results / "contact-sheet-compare.png"
    with Image.open(out) as im:
        assert im.height == 44 + len(rules_rows) * (240 + 2 * sheet.PAD)
        differs = rules_rows[0]["outcome"] != "needs_person"  # the fake agent hands everything off
        first_row_bar = im.getpixel((2, 44 + 100))
        assert (first_row_bar == sheet.DISAGREE) == differs
