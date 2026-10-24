"""Langkah 66: --help CLI eval untuk semua subperintah tidak boleh crash (tanda % di teks bantuan)."""

import argparse

import pytest

from mica.eval import __main__ as eval_cli


def _commands(
    parser: argparse.ArgumentParser, prefix: tuple[str, ...] = ()
) -> list[tuple[str, ...]]:
    """Semua jalur subperintah, termasuk yang bertingkat (dataset split, annotate export, ...)."""
    found = [prefix]
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                found.extend(_commands(sub, (*prefix, name)))
    return found


COMMANDS = _commands(eval_cli.build_parser())


def test_all_subcommands_found():
    names = {c[0] for c in COMMANDS if c}
    assert {"retrieval", "generation", "annotation", "labels", "dataset", "annotate"} <= names
    assert ("annotate", "export") in COMMANDS and ("dataset", "split") in COMMANDS


@pytest.mark.parametrize("command", COMMANDS, ids=lambda c: " ".join(c) or "(root)")
def test_help_does_not_crash(command, capsys):
    with pytest.raises(SystemExit) as exc:
        eval_cli.main([*command, "--help"])
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out
