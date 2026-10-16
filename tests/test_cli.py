import pytest

from printready.cli import main


def test_help_lists_command_groups(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for group in ("check", "fix", "bench", "realset", "mcp"):
        assert group in out


# No stub-exit tests here any more: bench and realset are implemented by their owners, and
# calling them from this file would run a real benchmark or paid image generation.


def test_size_must_be_positive():
    with pytest.raises(SystemExit) as exc:
        main(["check", "art.png", "--size", "0"])
    assert exc.value.code == 2
