"""Tests for ``hmp vacuum``."""

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
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return int(exc_info.value.code or 0)


def _make_workspace_with_catalog(tmp_path: Path) -> Path:
    from hydromodpy.results.catalog import SimulationCatalog

    workspace = tmp_path / "ws"
    workspace.mkdir()
    project = workspace / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "simulations").mkdir()
    (workspace / "data").mkdir()
    with SimulationCatalog(project):
        pass
    return workspace


def test_vacuum_help_displays(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "vacuum", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    assert "--catalog" in out
    assert "--cache" in out
    assert "--all" in out


def test_vacuum_basic_invocation(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    code = _run(monkeypatch, ["hmp", "vacuum", "--workspace", str(workspace)])
    assert code == 0
    out = capsys.readouterr().out
    assert "catalog_checkpoints" in out


def test_vacuum_catalog_only(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    code = _run(monkeypatch, ["hmp", "vacuum", "--workspace", str(workspace), "--catalog"])
    assert code == 0
    out = capsys.readouterr().out
    assert "CHECKPOINT" in out


def test_vacuum_cache_only_with_no_cache(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    code = _run(monkeypatch, ["hmp", "vacuum", "--workspace", str(workspace), "--cache"])
    assert code == 0
    out = capsys.readouterr().out
    # cache.duckdb missing -> 0 cache_checkpoints, still success
    assert "cache_checkpoints: 0" in out
