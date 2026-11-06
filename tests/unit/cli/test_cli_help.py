"""Every subcommand in ``hmp`` must expose a working ``--help``.

The tests drive :func:`hydromodpy.cli.main.main` directly so we catch
regressions in the argparse wiring without spawning a subprocess per case."""

from __future__ import annotations

import argparse
import importlib
import sys

import pytest

from hydromodpy.cli import banner
from hydromodpy.cli.commands import ALL_COMMANDS
from hydromodpy.cli.main import _build_parser
from tests.unit.cli._tree import commands


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


@pytest.mark.parametrize("words", [words for words, _ in commands()], ids=" ".join)
def test_each_command_has_a_help(monkeypatch, capsys, words: tuple[str, ...]) -> None:
    assert _run_help(monkeypatch, ["hmp", *words, "--help"]) == 0
    assert "usage" in capsys.readouterr().out.lower()


def test_the_color_changes_only_on_a_blank_column() -> None:
    """A split inside a stroke draws one letter in two colors."""
    for line, (hydro_end, mod_end) in zip(banner._LETTER_LINES, banner._SPLITS, strict=True):
        assert line[hydro_end - 1] == " ", line
        assert line[mod_end - 1] == " ", line


def test_the_footer_colors_the_strokes_and_dims_the_words() -> None:
    descender, tagline, swash = banner._FOOTER_SPLITS
    assert set(banner._FOOTER[descender:tagline]) == {"/", "_"}
    assert set(banner._FOOTER[swash:]) == {"/", "_"}
    assert banner._FOOTER[tagline:swash].strip() == "Hydrological Modelling in Python"


def test_the_banner_prints_the_whole_art() -> None:
    assert banner._banner().plain.splitlines() == [*banner._LETTER_LINES, banner._FOOTER]
