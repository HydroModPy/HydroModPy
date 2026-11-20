"""A run writes its own directory, and the index states what the sealed directories hold.

Each write method of a run store is read back through the index with plain SQL.
Budgets are volumes per time (m3/s), grid sizes are cell counts.
"""

from __future__ import annotations

import duckdb
import pandas as pd
import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.index_schema import INDEX_META_TABLE, META_SCHEMA_VERSION
from hydromodpy.schema.lineage import Lineage
from tests._helpers.run_builders import runs, write_plain_metric

__all__ = ["runs"]

BY_SIM_ID = "WHERE CAST(sim_id AS VARCHAR) = ?"


def fetch(catalog: Catalog, sql: str, sim_id: str) -> list[tuple]:
    return catalog.connection.execute(sql, [sim_id]).fetchall()


def test_an_index_of_another_schema_version_is_rebuilt_on_open(runs):
    sid = runs.open(project="test_project").sim_id
    runs.catalog()
    runs.close_catalog()
    index = runs.project_root / ".hmp" / "index.duckdb"
    with duckdb.connect(str(index)) as conn:
        conn.execute(
            f"UPDATE {INDEX_META_TABLE} SET value = '0' WHERE key = ?", [META_SCHEMA_VERSION]
        )

    with Catalog(runs.project_root) as catalog:
        [row] = fetch(
            catalog,
            "SELECT s.project, sv.code, st.code FROM simulations s "
            "JOIN solvers sv ON s.solver_id = sv.id JOIN statuses st ON s.status_id = st.id "
            "WHERE CAST(s.sim_id AS VARCHAR) = ?",
            sid,
        )
    assert row == ("test_project", "modflow6", "completed")


def test_parent_sim_id(runs):
    parent = runs.open().sim_id
    child = runs.open(lineage=Lineage(parent_sim_id=parent, kind="rerun")).sim_id

    [(recorded,)] = fetch(
        runs.catalog(),
        f"SELECT CAST(parent_sim_id AS VARCHAR) FROM simulations {BY_SIM_ID}",
        child,
    )

    assert recorded == parent


def test_an_empty_timeseries_writes_no_row(runs):
    store = runs.open()
    store.write_timeseries(store.sim_id, "P01", "head", pd.Series(dtype="float64"))

    rows = fetch(runs.catalog(), f"SELECT COUNT(*) FROM timeseries {BY_SIM_ID}", store.sim_id)

    assert rows == [(0,)]


def test_write_budget(runs):
    store = runs.open()
    store.write_budget(store.sim_id, 0, "zone_1", "recharge", 100.0, 0.0)
    store.write_budget(store.sim_id, 0, "zone_1", "drain", 0.0, 80.0)

    rows = fetch(runs.catalog(), f"SELECT COUNT(*) FROM budgets {BY_SIM_ID}", store.sim_id)

    assert rows == [(2,)]


def test_write_mass_balance(runs):
    store = runs.open()
    store.write_mass_balance(store.sim_id, 0, 100.0, 95.0, 5.0)
    store.write_mass_balance(store.sim_id, 1, 110.0, 108.0, 1.8)

    rows = fetch(
        runs.catalog(),
        f"SELECT timestep, percent_error FROM mass_balance {BY_SIM_ID} ORDER BY timestep",
        store.sim_id,
    )

    assert len(rows) == 2
    assert rows[0] == (0, 5.0)


def test_water_and_solute_budgets_coexist(runs):
    store = runs.open()
    store.write_mass_balances(store.sim_id, [{"timestep": 0, "percent_error": 1.0}])
    store.write_mass_balances(
        store.sim_id,
        [{"timestep": 0, "percent_error": 2.0, "quantity": "solute", "unit": "kg/s"}],
    )

    rows = fetch(
        runs.catalog(),
        f"SELECT quantity, unit, percent_error FROM mass_balance {BY_SIM_ID} ORDER BY quantity",
        store.sim_id,
    )

    # Same (sim_id, timestep) and no collision.
    assert rows == [("solute", "kg s-1", 2.0), ("water", "m3 s-1", 1.0)]


def test_a_grid_update_with_none_keeps_the_recorded_values(runs):
    store = runs.open()
    store.update_simulation_grid_metadata(
        store.sim_id,
        n_cells=3600,
        n_layers=2,
        mesh_hash="abc123",
        mesh_topology="structured_3d",
        bbox=[10.0, 20.0, 110.0, 220.0],
    )
    store.update_simulation_grid_metadata(store.sim_id, n_cells=None, mesh_hash=None)

    rows = fetch(
        runs.catalog(),
        "SELECT s.n_cells, s.n_layers, s.mesh_hash, mt.code, s.bbox_xmin, s.bbox_ymax "
        "FROM simulations s LEFT JOIN mesh_topologies mt ON mt.id = s.mesh_topology_id "
        "WHERE CAST(s.sim_id AS VARCHAR) = ?",
        store.sim_id,
    )

    assert rows == [(3600, 2, "abc123", "structured_3d", 10.0, 220.0)]


def test_a_metric_written_twice_keeps_the_last_value(runs):
    store = runs.open()
    write_plain_metric(store, "P01", "nse", 0.7)
    write_plain_metric(store, "P01", "nse", 0.85)

    rows = fetch(
        runs.catalog(),
        f"SELECT value FROM metrics {BY_SIM_ID} AND metric = 'nse'",
        store.sim_id,
    )

    assert len(rows) == 1
    assert rows[0][0] == pytest.approx(0.85)
