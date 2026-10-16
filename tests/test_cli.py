import pytest

from printready.cli import main


def test_help_lists_command_groups(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for group in ("check", "fix", "bench", "realset"):
        assert group in out


@pytest.mark.parametrize(
    "argv, chunk",
    [
        (["check", "art.png", "--size", "3"], "K1"),
        (["fix", "art.png", "--size", "3", "--mode", "agent"], "K3"),
        (["bench", "generate", "--split", "dev"], "K2"),
        (["bench", "run", "--mode", "rules"], "K2b"),
        (["bench", "report"], "K2b"),
        (["realset", "gen", "--prompts", "p.txt", "--image-model", "xai:grok-imagine-image", "--n", "1"], "K5"),
        (["realset", "label", "some/dir"], "K5"),
        (["realset", "eval", "some/dir"], "K5"),
    ],
)
def test_stubs_exit_2(argv, chunk, capsys):
    assert main(argv) == 2
    err = capsys.readouterr().err
    assert f"{argv[0]}: not implemented yet (chunk {chunk})" in err


def test_size_must_be_positive():
    with pytest.raises(SystemExit) as exc:
        main(["check", "art.png", "--size", "0"])
    assert exc.value.code == 2
