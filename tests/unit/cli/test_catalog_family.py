"""Tests for the ``hmp catalog`` family (ls, query, show, gc, vacuum, delete)."""

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


def test_catalog_family_help_lists_actions(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "catalog", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    for action in ("ls", "query", "show", "gc", "vacuum", "delete"):
        assert action in out


def test_catalog_ls_empty_workspace(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    code = _run(monkeypatch, ["hmp", "catalog", "ls", "--workspace", str(workspace)])
    assert code == 0


def test_catalog_query_missing_workspace_returns_not_found(monkeypatch, tmp_path) -> None:
    missing = tmp_path / "empty_ws"
    missing.mkdir()
    code = _run(
        monkeypatch,
        ["hmp", "catalog", "query", "SELECT 1", "--workspace", str(missing)],
    )
    assert code == 10


def test_catalog_query_runs_on_existing_catalog(monkeypatch, tmp_path, capsys) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    project = workspace / "projects" / "demo"
    code = _run(
        monkeypatch,
        ["hmp", "catalog", "query", "SELECT 1 AS one", "--workspace", str(project)],
    )
    assert code == 0
    out = capsys.readouterr().out
    assert "one" in out


def test_catalog_show_unknown_sim_returns_not_found(monkeypatch, tmp_path) -> None:
    workspace = _make_workspace_with_catalog(tmp_path)
    project = workspace / "projects" / "demo"
    code = _run(
        monkeypatch,
        ["hmp", "catalog", "show", "deadbeef", "--workspace", str(project)],
    )
    assert code == 10
