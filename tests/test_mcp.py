"""MCP tools: the tool functions are called directly; the server test needs the `mcp` extra."""

import asyncio
import json
from pathlib import Path

import pytest

from printready.cli import main
from printready.mcp_server import check_artwork, fix_artwork, get_rules

FIXTURES = Path(__file__).parent / "fixtures"


def test_check_artwork_returns_findings():
    result = check_artwork(str(FIXTURES / "badge-on-white.jpg"), 1.0)
    json.dumps(result)
    assert result["status"] == "fail" and result["ppi"] == pytest.approx(450)
    assert [f["check"] for f in result["findings"]][:3] == ["file", "resolution", "background"]
    bg = result["findings"][2]
    assert (bg["status"], bg["fixer"]) == ("fail", "auto")


def test_check_artwork_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        check_artwork(str(tmp_path / "missing.png"), 3)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"nope")
    assert check_artwork(str(bad), 3)["findings"][0]["status"] == "fail"


def test_fix_artwork_writes_outputs(tmp_path):
    result = fix_artwork(str(FIXTURES / "badge-on-white.jpg"), 1.0, str(tmp_path / "out"))
    json.dumps(result)
    assert result["outcome"] == "fixable"
    assert [s["fix"] for s in result["steps"]] == ["remove_background", "add_border"]
    assert result["steps"][0]["guard"]["metric"] == "damage_frac"
    assert all(Path(p).is_absolute() and Path(p).exists() for p in result["outputs"].values())
    assert {"fixed", "cutline", "proof", "report"} <= set(result["outputs"])


def test_fix_artwork_default_out_dir(tmp_path):
    art = tmp_path / "badge.png"
    art.write_bytes((FIXTURES / "badge.png").read_bytes())
    result = fix_artwork(str(art), 1.0)
    assert result["outcome"] == "ready"
    assert Path(result["outputs"]["proof"]).parent == tmp_path / "badge-printready"


def test_get_rules_has_sources():
    rules = get_rules()["rules"]
    assert rules["border_in"]["value"] == 0.1 and rules["border_in"]["source"].startswith("https://")
    assert rules["ppi_floor"]["source"] == "convention" and rules["ppi_floor"]["why"]


def test_server_lists_and_calls_tools():
    pytest.importorskip("mcp")
    from printready.mcp_server import build_server

    server = build_server()
    names = {t.name for t in asyncio.run(server.list_tools())}
    assert names == {"check_artwork", "fix_artwork", "get_rules"}
    result = asyncio.run(server.call_tool("get_rules", {}))
    assert "border_in" in json.dumps(result.model_dump(mode="json"))


def test_mcp_command_without_extra(monkeypatch, capsys):
    import builtins

    real_import = builtins.__import__

    def no_mcp(name, *args, **kwargs):
        if name == "mcp":
            raise ImportError("no mcp")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_mcp)
    assert main(["mcp"]) == 2 and "uv sync --extra mcp" in capsys.readouterr().err
