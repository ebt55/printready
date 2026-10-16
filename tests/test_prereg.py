"""prereg freeze / verify on a small fake checkout (offline; no git needed except the gate's check)."""

import pytest

from printready import agent, prereg
from printready.cli import main

FILES = {
    "profiles/stickermule-diecut.yaml": "name: x\n",
    "data/bench/manifest-dev.jsonl": '{"id": "clean-000"}\n',
    "realset/prompts.txt": "a sticker\n",
    "src/printready/__init__.py": "",
    "src/printready/agent.py": "MAX_TURNS = 8\n",
    "src/printready/bench/generate.py": "SEEDS = {}\n",
    "src/printready/bench/run.py": "RUNNER = 1\n",
    "src/printready/prompts/vision-text.md": "Read the text.\n",
    "src/printready/web/server.py": "WEB = 1\n",
}


@pytest.fixture
def repo(tmp_path):
    for rel, text in FILES.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return tmp_path


def test_freeze_creates_prereg_and_verify_passes(repo):
    path, snap = prereg.freeze(repo)
    text = path.read_text(encoding="utf-8")
    assert text.startswith("# Preregistration") and "TODO" in text
    assert prereg.START in text and prereg.END in text
    assert prereg.read_block(text) == snap
    paths = {v["path"] for v in snap["files"].values()}
    assert {"profiles/stickermule-diecut.yaml", "data/bench/manifest-dev.jsonl", "realset/prompts.txt",
            "src/printready/bench/generate.py", "src/printready/prompts/vision-text.md"} <= paths
    assert "src/printready/bench/run.py" not in paths  # the runner is not generator source
    source = snap["source"][prereg.SOURCE_GROUP]["files"]
    assert "src/printready/bench/run.py" in source and "src/printready/web/server.py" not in source
    assert snap["settings"]["agent_max_turns"] == agent.MAX_TURNS
    assert snap["settings"]["temperature"] == 0
    assert snap["settings"]["text_small_env"] == "PRINTREADY_TEXT_SMALL"
    assert snap["settings"]["text_small_default"] is False
    assert {"remove_background", "fit_shape", "finish", "handoff"} <= set(snap["settings"]["agent_tools"])
    assert prereg.verify(repo) == []


def test_verify_names_every_change(repo, monkeypatch):
    prereg.freeze(repo)
    (repo / "src/printready/bench/generate.py").write_text("SEEDS = {'dev': 1}\n", encoding="utf-8")
    (repo / "src/printready/prompts/agent-system.md").write_text("new prompt\n", encoding="utf-8")
    (repo / "data/bench/manifest-dev.jsonl").unlink()
    (repo / "src/printready/web/server.py").write_text("WEB = 2\n", encoding="utf-8")  # not frozen
    monkeypatch.setattr(agent, "MAX_TURNS", 9)
    problems = prereg.verify(repo)
    joined = "\n".join(problems)
    assert "CHANGED  src/printready/bench/generate.py (bench generator: generate.py)" in joined
    assert "CHANGED  src/printready/bench/generate.py (source)" in joined
    assert "NEW      src/printready/prompts/agent-system.md" in joined
    assert "MISSING  data/bench/manifest-dev.jsonl" in joined
    assert "SETTING  agent_max_turns: 8 -> 9" in joined
    assert "web" not in joined
    assert len(problems) == 5


def test_crlf_checkout_still_verifies(repo):
    prereg.freeze(repo)
    path = repo / "src/printready/agent.py"
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    assert prereg.verify(repo) == []


def test_refreeze_keeps_the_prose_and_is_idempotent(repo):
    (repo / "PREREG.md").write_text("# PREREG\n\n1. Frozen at commit: see below.\n", encoding="utf-8")
    prereg.freeze(repo)
    first = (repo / "PREREG.md").read_text(encoding="utf-8")
    assert first.startswith("# PREREG\n\n1. Frozen at commit") and first.count(prereg.START) == 1
    (repo / "PREREG.md").write_text(first + "\n8. What this cannot show.\n", encoding="utf-8")
    prereg.freeze(repo)
    second = (repo / "PREREG.md").read_text(encoding="utf-8")
    assert second.count(prereg.START) == 1 and second.endswith("8. What this cannot show.\n")
    assert prereg.read_block(second) == prereg.read_block(first)


def test_cli_verify_exit_codes(repo, capsys):
    assert main(["prereg", "verify", "--root", str(repo)]) == 1  # no PREREG.md yet
    assert main(["prereg", "freeze", "--root", str(repo)]) == 0
    assert main(["prereg", "verify", "--root", str(repo)]) == 0
    assert "OK" in capsys.readouterr().out
    (repo / "realset/prompts.txt").write_text("a different sticker\n", encoding="utf-8")
    assert main(["prereg", "verify", "--root", str(repo)]) == 1
    assert "CHANGED  realset/prompts.txt" in capsys.readouterr().err


def test_require_verified_needs_a_commit(repo):
    with pytest.raises(prereg.PreregError, match="does not exist"):
        prereg.require_verified(repo)
    prereg.freeze(repo)
    with pytest.raises(prereg.PreregError, match="not committed|could not run git"):
        prereg.require_verified(repo)  # tmp dir is not a git repository
