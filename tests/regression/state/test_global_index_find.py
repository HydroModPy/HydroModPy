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
from hydromodpy.core.state.paths import catalog_path_for
from hydromodpy.results.catalog.migrations import ensure_schema as _ensure_catalog


def _seed_real_catalog(project_root: Path, *, solver_code: str, project: str) -> str:
    """Materialise a real catalog DB with one simulation under ``solver_code``."""
    catalog_path = catalog_path_for(project_root)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
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
    project_root = tmp_path / "naizin"
    sim_id = _seed_real_catalog(project_root, solver_code="modflow6", project="naizin")

    with GlobalIndex(state_root / "index.duckdb") as index:
        index.register(str(project_root), label="naizin")
        index.refresh_federation()
        rows = index.find(solver="modflow6")

    assert len(rows) == 1
    assert str(rows.iloc[0]["sim_id"]) == sim_id
    assert rows.iloc[0]["solver"] == "modflow6"


def test_find_filters_on_solver_code(tmp_path: Path) -> None:
    """Two projects with different solvers: ``find`` returns only the match."""
    state_root = tmp_path / "state"
    project_a = tmp_path / "naizin"
    project_b = tmp_path / "lez"
    _seed_real_catalog(project_a, solver_code="modflow6", project="naizin")
    _seed_real_catalog(project_b, solver_code="boussinesq", project="lez")

    with GlobalIndex(state_root / "index.duckdb") as index:
        index.register(str(project_a), label="naizin")
        index.register(str(project_b), label="lez")
        index.refresh_federation()
        rows = index.find(solver="boussinesq")

    assert len(rows) == 1
    assert rows.iloc[0]["solver"] == "boussinesq"


def _seed_row(project_root: Path, *, name: str, status_code: str, nse: float | None = None) -> str:
    """Insert one simulation row (and optional nse metric) into a catalog."""
    catalog_path = catalog_path_for(project_root)
    catalog_path.parent.mkdir(parents=True, exist_ok=True)
    sim_id = str(uuid.uuid4())
    connection = duckdb.connect(str(catalog_path))
    try:
        _ensure_catalog(connection)
        solver_id = connection.execute("SELECT id FROM solvers WHERE code = 'modflow6'").fetchone()[
            0
        ]
        status_id = connection.execute(
            "SELECT id FROM statuses WHERE code = ?", [status_code]
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO simulations (sim_id, name, project, solver_id, status_id, "
            "zarr_path, storage_basename) VALUES (?, ?, 'cheze', ?, ?, ?, ?)",
            [sim_id, name, solver_id, status_id, "zarr/", name],
        )
        if nse is not None:
            connection.execute(
                "INSERT INTO metrics (sim_id, station_id, variable, metric_name, value) "
                "VALUES (?, '__outlet__', 'head', 'nse', ?)",
                [sim_id, nse],
            )
    finally:
        connection.close()
    return sim_id


def test_find_keyword_filters_hide_trashed_and_compare(tmp_path: Path) -> None:
    state_root = tmp_path / "state"
    project_root = tmp_path / "cheze"
    _seed_row(project_root, name="cheze_baseline", status_code="completed", nse=0.86)
    _seed_row(project_root, name="cheze_draft", status_code="trashed")

    with GlobalIndex(state_root / "index.duckdb") as index:
        index.register(str(project_root), label="cheze")
        index.refresh_federation()
        default = index.find()
        by_name = index.find(name_like="cheze_base%")
        trashed = index.find(status="trashed")
        good = index.find(nse_gt=0.8)
        none = index.find(nse_gt=0.95)

    # trashed runs are hidden unless explicitly requested
    assert set(default["status"]) == {"completed"}
    assert list(by_name["name"]) == ["cheze_baseline"]
    assert list(trashed["status"]) == ["trashed"]
    # comparison operator on a metric column
    assert list(good["name"]) == ["cheze_baseline"]
    assert none.empty
