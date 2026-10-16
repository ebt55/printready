import json
from pathlib import Path

from printready.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_fix_rules_on_fixture(tmp_path, capsys):
    code = main(["fix", str(FIXTURES / "badge-on-white.jpg"), "--size", "1", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert out.splitlines()[1].startswith("FIXABLE")
    assert "background   fail -> pass" in out and "step remove_background" in out
    data = json.loads((tmp_path / "badge-on-white" / "report.json").read_text(encoding="utf-8"))
    assert data["outcome"] == "fixable" and data["mode"] == "rules"


def test_fix_needs_person_exits_1(tmp_path):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"nope")
    assert main(["fix", str(bad), "--size", "3", "--out", str(tmp_path / "out")]) == 1


def test_fix_agent_reports_when_not_available(tmp_path, monkeypatch, capsys):
    import printready.agent as agent
    import printready.llm as llm

    def not_yet(*args, **kwargs):
        raise NotImplementedError("K4")

    monkeypatch.setattr(llm, "make_client", lambda model: object(), raising=False)
    monkeypatch.setattr(agent, "run_agent", not_yet, raising=False)
    code = main(["fix", str(FIXTURES / "badge.png"), "--size", "1", "--mode", "agent", "--out", str(tmp_path)])
    assert code == 2 and "not implemented yet (chunk K4)" in capsys.readouterr().err


def test_fix_size_too_small(tmp_path, capsys):
    assert main(["fix", str(FIXTURES / "badge.png"), "--size", "0.2", "--out", str(tmp_path)]) == 2
    assert "no room" in capsys.readouterr().err
