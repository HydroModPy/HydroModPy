"""Unit tests for the ``hmp.catalog`` facade."""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb
import pytest

from hydromodpy.catalog import CatalogFacade, open_catalog


def _seed_catalog(workspace: Path, *, solver: str = "modflow6") -> str:
    from hydromodpy.results.catalog.migrations import ensure_schema as _ensure_catalog

    workspace.mkdir(parents=True, exist_ok=True)
    catalog_path = workspace / "catalog.duckdb"
    sim_id = str(uuid.uuid4())
    connection = duckdb.connect(str(catalog_path))
    try:
        _ensure_catalog(connection)
        solver_id = connection.execute(
            "SELECT id FROM solvers WHERE code = ?", [solver]
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO simulations
                (sim_id, name, project, solver_id, status_id, zarr_path, storage_basename)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            [sim_id, "demo", "naizin", solver_id, "zarr/", "demo"],
        )
    finally:
        connection.close()
    return sim_id


def test_open_catalog_returns_facade(tmp_path: Path) -> None:
    """``open_catalog`` resolves to a usable facade against an explicit workspace."""
    workspace = tmp_path / "naizin"
    workspace.mkdir()
    with open_catalog(workspace) as cat:
        assert isinstance(cat, CatalogFacade)
        assert cat.workspace == workspace.resolve()


def test_open_catalog_honours_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """``HMP_WORKSPACE`` becomes the default workspace path."""
    workspace = tmp_path / "via_env"
    workspace.mkdir()
    monkeypatch.setenv("HMP_WORKSPACE", str(workspace))
    cat = open_catalog()
    try:
        assert cat.workspace == workspace.resolve()
    finally:
        cat.close()


def test_simulations_find_returns_inserted_row(tmp_path: Path) -> None:
    """``cat.simulations.find()`` surfaces the catalog through the facade."""
    workspace = tmp_path / "naizin"
    sim_id = _seed_catalog(workspace, solver="modflow6")
    with open_catalog(workspace) as cat:
        rows = cat.simulations.find(solver="modflow6")
    assert len(rows) == 1
    assert str(rows.iloc[0]["sim_id"]) == sim_id


def test_simulations_get_returns_one_row(tmp_path: Path) -> None:
    """``cat.simulations.get(sim_id)`` returns exactly one row."""
    workspace = tmp_path / "naizin"
    sim_id = _seed_catalog(workspace)
    with open_catalog(workspace) as cat:
        rows = cat.simulations.get(sim_id)
    assert len(rows) == 1


def test_simulations_filter_drops_unknown_columns(tmp_path: Path) -> None:
    """Filters keyed by unknown columns are silently ignored, not errors."""
    workspace = tmp_path / "naizin"
    _seed_catalog(workspace)
    with open_catalog(workspace) as cat:
        rows = cat.simulations.find(banana_color="yellow", solver="modflow6")
    assert len(rows) == 1


def test_simulations_has_catalog_false_when_missing(tmp_path: Path) -> None:
    """The boolean helper reports ``False`` on a fresh workspace."""
    workspace = tmp_path / "empty"
    workspace.mkdir()
    with open_catalog(workspace) as cat:
        assert cat.simulations.has_catalog() is False


def test_inputs_has_cache_false_when_missing(tmp_path: Path) -> None:
    """``inputs.has_cache()`` is False until ``data/cache.duckdb`` exists."""
    workspace = tmp_path / "naizin"
    workspace.mkdir()
    with open_catalog(workspace) as cat:
        assert cat.inputs.has_cache() is False
        assert cat.inputs.db_path == (workspace.resolve() / "data" / "cache.duckdb")
