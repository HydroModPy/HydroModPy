"""Smoke tests for the argcomplete wiring on the ``hmp`` parser."""

from __future__ import annotations

import argparse
import importlib

import pytest


def _cli_main_module():
    """Return the ``hydromodpy.cli.main`` module (not the re-exported function)."""
    return importlib.import_module("hydromodpy.cli.main")


def test_enable_argcomplete_invokes_autocomplete(monkeypatch: pytest.MonkeyPatch) -> None:
    """``_enable_argcomplete`` calls ``argcomplete.autocomplete`` when available."""
    cli_main = _cli_main_module()

    captured: list[argparse.ArgumentParser] = []

    class _StubArgcomplete:
        @staticmethod
        def autocomplete(parser: argparse.ArgumentParser) -> None:
            captured.append(parser)

    monkeypatch.setitem(__import__("sys").modules, "argcomplete", _StubArgcomplete)

    parser = argparse.ArgumentParser(prog="hmp")
    cli_main._enable_argcomplete(parser)

    assert captured == [parser]


def test_enable_argcomplete_silent_when_dep_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing ``argcomplete`` import must not crash the CLI."""
    import builtins
    import sys

    cli_main = _cli_main_module()

    monkeypatch.delitem(sys.modules, "argcomplete", raising=False)
    real_import = builtins.__import__

    def _block_argcomplete(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "argcomplete":
            raise ImportError("simulated absence")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _block_argcomplete)

    parser = argparse.ArgumentParser(prog="hmp")
    cli_main._enable_argcomplete(parser)


def test_main_parser_is_argcomplete_ok() -> None:
    """The CLI main module exposes the ``PYTHON_ARGCOMPLETE_OK`` magic marker."""
    import pathlib

    cli_main = _cli_main_module()

    source = pathlib.Path(cli_main.__file__).read_text(encoding="utf-8")
    assert "PYTHON_ARGCOMPLETE_OK" in source


def test_run_subparser_step_completer_is_attached() -> None:
    """``hmp run --from`` carries an argcomplete ``ChoicesCompleter`` when available."""
    pytest.importorskip("argcomplete")

    from hydromodpy.cli.commands import run as run_command

    parser = argparse.ArgumentParser(prog="hmp")
    sub = parser.add_subparsers()
    run_command.register(sub)

    run_parser = sub.choices["run"]
    from_action = next(a for a in run_parser._actions if "--from" in a.option_strings)
    assert hasattr(from_action, "completer")
