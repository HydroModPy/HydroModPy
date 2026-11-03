"""Every subcommand in ``hmp`` must expose a working ``--help``.

The tests drive :func:`hydromodpy.cli.main.main` directly so we catch
regressions in the argparse wiring without spawning a subprocess per case.
"""

from __future__ import annotations

import argparse
import importlib
import sys

import pytest

from hydromodpy.cli.commands import ALL_COMMANDS
from hydromodpy.cli.conventions import OldVerb
from hydromodpy.cli.main import _build_parser


def _load_module():
    return importlib.import_module("hydromodpy.cli.main")


SUBCOMMANDS = [
    getattr(module, "NAME", module.__name__.rsplit(".", 1)[-1]) for module in ALL_COMMANDS
]


def _run_help(monkeypatch, argv: list[str]) -> int:
    module = _load_module()
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def test_top_level_help(monkeypatch, capsys) -> None:
    code = _run_help(monkeypatch, ["hmp", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    for cmd in SUBCOMMANDS:
        assert cmd in out, f"{cmd} missing from top-level --help"


def _commands(parser: argparse.ArgumentParser, words: tuple[str, ...] = ()):
    if isinstance(parser, OldVerb):
        return
    yield words
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                yield from _commands(child, (*words, name))


@pytest.mark.parametrize("words", list(_commands(_build_parser())), ids=" ".join)
def test_each_command_has_a_help(monkeypatch, capsys, words: tuple[str, ...]) -> None:
    assert _run_help(monkeypatch, ["hmp", *words, "--help"]) == 0
    assert "usage" in capsys.readouterr().out.lower()
