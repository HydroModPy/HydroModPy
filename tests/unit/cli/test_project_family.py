"""Tests for the ``hmp project`` family (new, list, show, delete)."""

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


def _make_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "data").mkdir()
    (workspace / "projects").mkdir()
    return workspace


def test_project_family_help_lists_actions(monkeypatch, capsys) -> None:
    code = _run(monkeypatch, ["hmp", "project", "--help"])
    assert code == 0
    out = capsys.readouterr().out
    for action in ("new", "list", "show", "delete"):
        assert action in out


def test_project_new_scaffolds_project(monkeypatch, capsys, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["hmp", "project", "new", "demo", "--workspace", str(workspace)],
    )
    main = _load_main().main
    main()
    assert (workspace / "projects" / "demo").is_dir()


def test_project_list_empty_workspace(monkeypatch, capsys, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    monkeypatch.setattr(sys, "argv", ["hmp", "project", "list", "--workspace", str(workspace)])
    _load_main().main()
    out = capsys.readouterr().out
    assert "no projects" in out.lower() or "workspace" in out.lower()


def test_project_show_missing_project_returns_not_found(monkeypatch, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    code = _run(
        monkeypatch,
        ["hmp", "project", "show", "missing", "--workspace", str(workspace)],
    )
    assert code == 10


def test_project_delete_force_removes_project_directory(monkeypatch, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    project_dir = workspace / "projects" / "demo"
    project_dir.mkdir(parents=True)
    (project_dir / "marker.txt").write_text("hello")

    code = _run(
        monkeypatch,
        ["hmp", "project", "delete", "demo", "--workspace", str(workspace), "-y"],
    )
    assert code == 0
    assert not project_dir.exists()


def test_project_delete_refuses_without_force_in_non_tty(monkeypatch, tmp_path) -> None:
    workspace = _make_workspace(tmp_path)
    project_dir = workspace / "projects" / "demo"
    project_dir.mkdir(parents=True)

    code = _run(
        monkeypatch,
        ["hmp", "project", "delete", "demo", "--workspace", str(workspace)],
    )
    assert code == 130
    assert project_dir.exists()
