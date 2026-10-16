"""analysis/prompt_prefix.py (exploratory, post hoc) with a fake image client: no network."""

import base64
import importlib.util
import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from printready import realset
from printready.llm import ChatClient, FakeTransport
from printready.spend import Price

SPEC = importlib.util.spec_from_file_location("prompt_prefix",
                                              Path(__file__).resolve().parents[1] / "analysis" / "prompt_prefix.py")
pp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pp)


def jpeg(kind: str, seed: int) -> bytes:
    if kind == "scene":  # no plain background: a gradient over the whole canvas
        yy, xx = np.mgrid[0:240, 0:240]
        img = np.dstack([xx, yy, np.full_like(xx, 90 + seed)]).astype(np.uint8)
    else:  # a sticker on white
        img = np.full((240, 240, 3), 255, np.uint8)
        cv2.circle(img, (120, 120), 70 + seed, (40, 90, 160), -1)
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def fake_generator(kinds, prompts_seen):
    """generate_image's signature, served by the fake provider (one scripted image per call)."""
    responses = [{"b64_json": base64.b64encode(jpeg(k, i)).decode()} for i, k in enumerate(kinds)]
    client = ChatClient("fake:images", FakeTransport(responses), price=Price())

    def gen(model, prompt, **opts):
        prompts_seen.append(prompt)
        return client.image(prompt, **opts)
    return gen


def tree(tmp_path):
    (tmp_path / "realset").mkdir()
    (tmp_path / "realset" / "prompts.txt").write_text("# test\na cat\na dog\na fox\n", encoding="utf-8")
    unprefixed = [  # the same model's original test runs: two scenes, one die-cut
        {"image": f"{i:064x}", "prompt_id": f"p{i + 1:02d}", "image_model": pp.MODEL, "outcome": "fixable",
         "shape": shape, "after": {"background": {"status": "pass", "fixer": "none"},
                                   "text_garbled": {"status": "skip", "fixer": "none"}}}
        for i, shape in enumerate(["rounded_rect", "rounded_rect", "die_cut"])]
    realset.append_jsonl(tmp_path / "results" / "realset" / "test" / "rules" / "runs.jsonl", unprefixed)
    return tmp_path


def test_estimate_only_without_yes(tmp_path):
    root = tree(tmp_path)
    seen = []
    assert pp.main(["--root", str(root)], gen=fake_generator(["sticker"] * 3, seen)) == 2
    assert seen == [] and not (root / "data" / "realset" / "prefix" / "manifest.jsonl").exists()


def test_prefixed_images_are_generated_judged_and_compared_with_a_hard_stop(tmp_path, capsys):
    root = tree(tmp_path)
    seen = []
    gen = fake_generator(["sticker", "scene", "sticker"], seen)
    assert pp.main(["--root", str(root), "--yes", "--max-usd", "0.05"], gen=gen) == 0  # $0.02 each: stops after 2
    assert seen == [pp.PREFIX + "a cat", pp.PREFIX + "a dog"]
    manifest = realset.read_jsonl(root / "data" / "realset" / "prefix" / "manifest.jsonl")
    assert [e["prompt_id"] for e in manifest] == ["p01", "p02"] and all(e["full_prompt"].startswith(pp.PREFIX) for e in manifest)
    assert pp.main(["--root", str(root), "--yes", "--max-usd", "0.10"], gen=gen) == 0  # resumes: only p03
    assert len(seen) == 3
    rows = realset.last_by(realset.read_jsonl(root / "results" / "realset" / "prefix" / "runs.jsonl"), "prompt_id")
    assert {p: pp.product(r) for p, r in rows.items()} == {"p01": "die_cut", "p02": "rounded_rect", "p03": "die_cut"}
    c = pp.compare(root)
    assert c["n"] == 3 and c["moves"][("rounded_rect", "die_cut")] == 1 and c["text_errors_unprefixed"] == 3
    md = (root / "results" / "realset" / "prefix" / "prefix.md").read_text(encoding="utf-8")
    assert pp.CAVEAT in md and "| rounded rect | 2 (67%) | 1 (33%) |" in md
    assert (root / "results" / "realset" / "prefix" / "contact-sheet.jpg").exists()
