"""A ``soil_budget`` row names exactly what it holds: no silent extra column."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from hydromodpy.core.state.paths import PROJECT_MARKER_FILENAME
from hydromodpy.results.catalog import Catalog
from hydromodpy.results.storage.parquet_schemas import primary_key_for


def _register(catalog: Catalog) -> str:
    sid = str(uuid.uuid4())
    reg = catalog.register_simulation(sid, project="demo", solver="modflow6", n_cells=1, n_layers=1)
    if reg.zarr is not None:
        reg.zarr.close()
    return sid


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / PROJECT_MARKER_FILENAME).write_text("[workspace]\n", encoding="utf-8")
    return project


def test_soil_budget_declares_its_primary_key() -> None:
    assert primary_key_for("soil_budget") == ("sim_id", "column_id", "year")


def test_an_undeclared_column_is_refused_by_name(tmp_path: Path) -> None:
    with Catalog(_project(tmp_path)) as catalog:
        sid = _register(catalog)
        with pytest.raises(KeyError, match="not_a_column"):
            catalog.write_view(
                sid,
                "soil_budget",
                [{"column_id": "0.0", "year": 2020, "not_a_column": 1.0}],
            )
