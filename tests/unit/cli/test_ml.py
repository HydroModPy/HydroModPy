"""Tests for ``hmp ml`` stubs."""

from __future__ import annotations

import importlib
import sys

import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def test_ml_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "ml", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    for sub in ("split", "fit-scaler", "export", "track"):
        assert sub in out


@pytest.mark.parametrize(
    "subcommand",
    ["split", "fit-scaler", "export", "track"],
)
def test_ml_subcommand_prints_ready_to_go(monkeypatch, capsys, subcommand) -> None:
    code = _run(monkeypatch, ["hmp", "ml", subcommand])
    assert code == 0
    out = capsys.readouterr().out
    assert "ready-to-go" in out


def test_ml_unknown_subcommand_fails(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "ml"])
    assert code == 1
    err = capsys.readouterr().err
    assert "Usage" in err
