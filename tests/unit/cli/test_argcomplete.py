"""Smoke tests for the argcomplete wiring on the ``hmp`` parser."""

from __future__ import annotations

import argparse
import importlib

import pytest


def _cli_main_module():
    """Return the ``hydromodpy.cli.main`` module (not the re-exported function)."""
    return importlib.import_module("hydromodpy.cli.main")


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


@pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
def test_completion_prints_the_script_argcomplete_writes(capsys, shell: str) -> None:
    """``hmp completion SHELL`` lists no command itself: it prints what argcomplete prints."""
    pytest.importorskip("argcomplete")
    import argcomplete

    from hydromodpy.cli.commands import completion

    completion.run(argparse.Namespace(shell=shell))

    printed = capsys.readouterr().out
    assert printed == argcomplete.shellcode(["hmp", "hydromodpy"], shell=shell)
    assert "hmp" in printed and "hydromodpy" in printed
