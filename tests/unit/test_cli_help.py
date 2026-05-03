"""Every subcommand in ``hmp`` must expose a working ``--help``.

The tests drive :func:`hydromodpy._cli.main.main` directly so we catch
regressions in the argparse wiring without spawning a subprocess per case.
"""

from __future__ import annotations

import importlib
import sys

import pytest

from hydromodpy._cli.commands import ALL_COMMANDS


def _load_module():
    return importlib.import_module("hydromodpy._cli.main")


SUBCOMMANDS = [
    getattr(module, "NAME", module.__name__.rsplit(".", 1)[-1])
    for module in ALL_COMMANDS
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


@pytest.mark.parametrize("subcommand", SUBCOMMANDS)
def test_subcommand_help(monkeypatch, capsys, subcommand: str) -> None:
    code = _run_help(monkeypatch, ["hmp", subcommand, "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "usage" in out.lower()


def test_data_subcommands_help(monkeypatch, capsys) -> None:
    for sub in ("check", "list", "add"):
        code = _run_help(monkeypatch, ["hmp", "data", sub, "--help"])
        assert code == 0, f"data {sub} --help failed"
        out = capsys.readouterr().out
        assert "usage" in out.lower()


def test_lock_subcommands_help(monkeypatch, capsys) -> None:
    for sub in ("update", "archive", "restore", "verify"):
        code = _run_help(monkeypatch, ["hmp", "lock", sub, "--help"])
        assert code == 0, f"lock {sub} --help failed"
        out = capsys.readouterr().out
        assert "usage" in out.lower()


def test_config_subcommands_help(monkeypatch, capsys) -> None:
    for sub in ("template", "check", "wizard"):
        code = _run_help(monkeypatch, ["hmp", "config", sub, "--help"])
        assert code == 0, f"config {sub} --help failed"
        out = capsys.readouterr().out
        assert "usage" in out.lower()


def test_version_flag(monkeypatch, capsys) -> None:
    code = _run_help(monkeypatch, ["hmp", "--version"])
    assert code == 0
    out = capsys.readouterr().out
    assert "hydromodpy" in out.lower()
