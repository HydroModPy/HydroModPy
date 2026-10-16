"""Inspecting a project never writes to its index."""

from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.catalog import Catalog, rebuild_index
from tests._helpers.sealed_runs import make_project, seal_run


def _run(monkeypatch, argv: list[str]) -> int:
    module = importlib.import_module("hydromodpy.cli.main")
    monkeypatch.setattr(sys, "argv", argv)
    try:
        module.main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def project(tmp_path) -> Path:
    root = make_project(tmp_path / "demo")
    seal_run(root, "alpha", mesh_engine=None)
    seal_run(root, "voronoi_run", mesh_engine="voronoi", config_text='[mesh]\nengine = "voronoi"\n')
    rebuild_index(root)
    return root


@pytest.mark.parametrize(
    "argv",
    [
        ["hmp", "catalog", "ls"],
        ["hmp", "catalog", "show", "alpha"],
        ["hmp", "catalog", "query", "SELECT COUNT(*) FROM simulations"],
    ],
)
def test_inspecting_leaves_the_index_byte_for_byte(monkeypatch, project, argv) -> None:
    index = catalog_path_for(project)
    before = _digest(index)
    mtime = index.stat().st_mtime_ns

    assert _run(monkeypatch, [*argv, "--workspace", str(project)]) == 0

    assert _digest(index) == before
    assert index.stat().st_mtime_ns == mtime


def test_a_reader_refuses_to_write(project) -> None:
    with Catalog(project) as catalog:
        with pytest.raises(Exception, match="read-only|Cannot execute|read_only"):
            catalog.backend.execute("DELETE FROM simulations")


def test_a_reader_never_creates_an_index(tmp_path) -> None:
    empty = make_project(tmp_path / "empty")

    with pytest.raises(FileNotFoundError, match="reindex"):
        Catalog(empty)
    assert not catalog_path_for(empty).exists()


def test_ls_shows_a_dash_for_a_run_with_no_mesh_engine(monkeypatch, project, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "catalog", "ls", "--workspace", str(project)]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if "alpha" in line]
    assert len(lines) == 1
    assert "mesh=-" in lines[0]


def test_ls_shows_the_mesh_engine_of_a_run(monkeypatch, project, capsys) -> None:
    assert _run(monkeypatch, ["hmp", "catalog", "ls", "--workspace", str(project)]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if "voronoi_run" in line]
    assert len(lines) == 1
    assert "mesh=voronoi" in lines[0]
