"""Tests for the ``hmp workspace`` family (init, list, clean)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


def _load_main():
    return importlib.import_module("hydromodpy.cli.main")


def _run(monkeypatch, argv: list[str]) -> int:
    module = _load_main()
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def test_workspace_family_help_lists_actions(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "workspace", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    for action in ("init", "list", "clean"):
        assert action in out


def test_workspace_init_scaffolds_workspace(monkeypatch, tmp_path) -> None:
    target = tmp_path / "fresh_ws"
    monkeypatch.setattr(sys, "argv", ["hmp", "workspace", "init", "--path", str(target)])
    _load_main().main()
    assert target.is_dir()
    assert (target / "projects").is_dir()
    assert (target / "data").is_dir()


def test_workspace_clean_requires_a_group(monkeypatch, capsys, tmp_path) -> None:
    target = tmp_path / "ws"
    target.mkdir()
    (target / "data").mkdir()
    code = _run(
        monkeypatch,
        ["hmp", "workspace", "clean", "--workspace", str(target)],
    )
    assert code == 14
    err = capsys.readouterr().err
    assert "group" in err.lower() or "--all" in err
