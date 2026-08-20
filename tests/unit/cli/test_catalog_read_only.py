"""Inspecting a project never writes to its index."""

from __future__ import annotations

import hashlib
import importlib
import sys
import uuid
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.catalog import Catalog


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
    root = tmp_path / "demo"
    root.mkdir()
    (root / "project.toml").write_text("[workspace]\nproject_root = '.'\n")
    with Catalog(root) as catalog:
        sid = str(uuid.uuid4())
        registration = catalog.register_simulation(
            sid,
            project="demo",
            solver="modflow6",
            name="alpha",
            n_cells=32,
            n_layers=1,
        )
        if registration.zarr is not None:
            registration.zarr.close()
        catalog.finalize(sid, status="completed", duration_s=1.0)
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

    code = _run(monkeypatch, [*argv, "--workspace", str(project)])

    assert code == 0
    assert _digest(index) == before


def test_a_read_only_catalog_refuses_to_write(project) -> None:
    with Catalog(project, read_only=True) as catalog:
        with pytest.raises(Exception, match="read-only|Read-only|read only"):
            catalog.backend.execute("DELETE FROM simulations")


def test_a_read_only_open_never_creates_an_index(tmp_path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(FileNotFoundError):
        Catalog(empty, read_only=True)

    assert not catalog_path_for(empty).exists()


def test_rendering_a_figure_never_creates_an_index(tmp_path) -> None:
    from hydromodpy.cli._workers.viz import render_figure

    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "project.toml").write_text("[workspace]\nproject_root = '.'\n")

    with pytest.raises(FileNotFoundError):
        render_figure("alpha", "piezometric_map", workspace=empty)

    assert not catalog_path_for(empty).exists()
