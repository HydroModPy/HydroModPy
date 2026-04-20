"""Every subcommand in ``hmp`` must expose a working ``--help``.

The tests drive ``hmp.__main__.main`` directly so we catch regressions in
the argparse wiring without spawning a subprocess per case.
"""

from __future__ import annotations

import importlib

import pytest


def _load_module():
    return importlib.import_module("hydromodpy.__main__")


SUBCOMMANDS = [
    "init",
    "new",
    "config",
    "run",
    "display",
    "list",
    "export",
    "test",
    "data",
    "show",
    "compare",
    "import",
    "calibrate",
]


def _run_help(monkeypatch, argv: list[str]) -> int:
    module = _load_module()
    monkeypatch.setattr(module.sys, "argv", argv)
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
