import json
from pathlib import Path

from printready.cli import main

FIXTURES = Path(__file__).parent / "fixtures"


def test_check_clean_badge_writes_outputs(tmp_path, capsys):
    code = main(["check", str(FIXTURES / "badge.png"), "--size", "1", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert code == 0
    assert "overall: pass (6 pass)" in out and "resolution" in out
    data = json.loads((tmp_path / "badge" / "report.json").read_text(encoding="utf-8"))
    assert data["spec"]["size_in"] == 1.0 and data["profile"] == "stickermule-diecut"
    assert [f["status"] for f in data["report"]["findings"]] == ["pass"] * 6
    assert (tmp_path / "badge" / "overlay.png").exists()


def test_check_opaque_white_background_fails(tmp_path, capsys):
    code = main(["check", str(FIXTURES / "badge-on-white.jpg"), "--size", "1", "--out", str(tmp_path)])
    assert code == 1
    data = json.loads((tmp_path / "badge-on-white" / "report.json").read_text(encoding="utf-8"))
    bg = next(f for f in data["report"]["findings"] if f["check"] == "background")
    assert (bg["status"], bg["fixer"]) == ("fail", "auto")
    assert "background" in capsys.readouterr().out


def test_check_undecodable_file_is_a_file_fail(tmp_path):
    bad = tmp_path / "broken.png"
    bad.write_bytes(b"\x89PNG but not really")
    assert main(["check", str(bad), "--size", "3", "--out", str(tmp_path / "out")]) == 1
    data = json.loads((tmp_path / "out" / "broken" / "report.json").read_text(encoding="utf-8"))
    f = data["report"]["findings"][0]
    assert (f["check"], f["status"], f["fixer"]) == ("file", "fail", "none")
    assert data["art"] is None
    assert not (tmp_path / "out" / "broken" / "overlay.png").exists()


def test_check_size_too_small_for_border(tmp_path, capsys):
    assert main(["check", str(FIXTURES / "badge.png"), "--size", "0.2", "--out", str(tmp_path)]) == 2
    assert "no room" in capsys.readouterr().err
