"""Regression: ``GlobalIndex.find(solver=...)`` against a real catalog.

The legacy code path filtered on a literal ``solver`` column, which only
exists in the simplified test fixtures. Real catalogs declare
``solver_id`` and join the ``solvers`` dimension. The V1 fix exposes a
``v_simulation_summary`` view with a textual ``solver`` code; the
federation prefers that view when present.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb

from hydromodpy.core.state.global_index import GlobalIndex
from hydromodpy.results.catalog.migrations import ensure_schema as _ensure_catalog


def _seed_real_catalog(workspace: Path, *, solver_code: str, project: str) -> str:
    """Materialise a real catalog DB with one simulation under ``solver_code``."""
    catalog_path = workspace / "catalog.duckdb"
    workspace.mkdir(parents=True, exist_ok=True)
    sim_id = str(uuid.uuid4())
    connection = duckdb.connect(str(catalog_path))
    try:
        _ensure_catalog(connection)
        solver_id = connection.execute(
            "SELECT id FROM solvers WHERE code = ?", [solver_code]
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO simulations
                (sim_id, name, project, solver_id, status_id,
                 zarr_path, storage_basename)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            [sim_id, "baseline", project, solver_id, "zarr/", "baseline"],
        )
    finally:
        connection.close()
    return sim_id


def test_find_returns_rows_for_real_catalog_solver(tmp_path: Path) -> None:
    """``find(solver="modflow6")`` returns the simulation registered under it."""
    state_root = tmp_path / "state"
    workspace = tmp_path / "naizin"
    sim_id = _seed_real_catalog(workspace, solver_code="modflow6", project="naizin")

    with GlobalIndex(state_root / "index.duckdb") as index:
        index.register_workspace(str(workspace), label="naizin")
        index.refresh_federation()
        rows = index.find(solver="modflow6")

    assert len(rows) == 1
    assert str(rows.iloc[0]["sim_id"]) == sim_id
    assert rows.iloc[0]["solver"] == "modflow6"


def test_find_filters_on_solver_code(tmp_path: Path) -> None:
    """Two workspaces with different solvers: ``find`` returns only the match."""
    state_root = tmp_path / "state"
    ws_a = tmp_path / "naizin"
    ws_b = tmp_path / "lez"
    _seed_real_catalog(ws_a, solver_code="modflow6", project="naizin")
    _seed_real_catalog(ws_b, solver_code="boussinesq", project="lez")

    with GlobalIndex(state_root / "index.duckdb") as index:
        index.register_workspace(str(ws_a), label="naizin")
        index.register_workspace(str(ws_b), label="lez")
        index.refresh_federation()
        rows = index.find(solver="boussinesq")

    assert len(rows) == 1
    assert rows.iloc[0]["solver"] == "boussinesq"
