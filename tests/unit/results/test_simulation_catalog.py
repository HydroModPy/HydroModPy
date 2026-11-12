"""A run writes its own directory; the index states what the sealed directories hold."""

from __future__ import annotations

import pandas as pd
import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.schema.lineage import Lineage
from tests._helpers.run_builders import runs, write_plain_metric

__all__ = ["runs"]


_SIM_SELECT = (
    "SELECT s.project, sv.code AS solver, st.code AS status, "
    "sv.category AS solver_category, s.duration_s "
    "FROM simulations s "
    "JOIN solvers sv ON s.solver_id = sv.id "
    "JOIN statuses st ON s.status_id = st.id "
    "WHERE CAST(s.sim_id AS VARCHAR) = ?"
)


def _one(catalog: Catalog, sql: str, sid: str) -> tuple:
    return catalog.connection.execute(sql, [sid]).fetchone()


class TestOpeningBuildsTheIndex:
    def test_an_index_of_another_schema_version_is_rebuilt_on_open(self, runs):
        import duckdb

        from hydromodpy.results.catalog.index_schema import INDEX_META_TABLE, META_SCHEMA_VERSION

        sid = runs.open(project="test_project").sim_id
        runs.catalog()
        runs.close_catalog()
        index = runs.project_root / ".hmp" / "index.duckdb"
        with duckdb.connect(str(index)) as conn:
            conn.execute(
                f"UPDATE {INDEX_META_TABLE} SET value = '0' WHERE key = ?", [META_SCHEMA_VERSION]
            )

        with Catalog(runs.project_root) as catalog:
            assert _one(catalog, _SIM_SELECT, sid)[:3] == ("test_project", "modflow6", "completed")


class TestSealAndIndex:
    def test_parent_sim_id(self, runs):
        parent = runs.open().sim_id
        child = runs.open(lineage=Lineage(parent_sim_id=parent, kind="rerun")).sim_id
        row = _one(
            runs.catalog(),
            "SELECT CAST(parent_sim_id AS VARCHAR) FROM simulations "
            "WHERE CAST(sim_id AS VARCHAR) = ?",
            child,
        )
        assert row[0] == parent


class TestWriteMethods:
    def test_write_timeseries_empty(self, runs):
        store = runs.open()
        store.write_timeseries(store.sim_id, "P01", "head", pd.Series(dtype="float64"))
        count = _one(
            runs.catalog(),
            "SELECT COUNT(*) FROM timeseries WHERE CAST(sim_id AS VARCHAR) = ?",
            store.sim_id,
        )[0]
        assert count == 0

    def test_write_budget(self, runs):
        store = runs.open()
        store.write_budget(store.sim_id, 0, "zone_1", "recharge", 100.0, 0.0)
        store.write_budget(store.sim_id, 0, "zone_1", "drain", 0.0, 80.0)
        count = _one(
            runs.catalog(),
            "SELECT COUNT(*) FROM budgets WHERE CAST(sim_id AS VARCHAR) = ?",
            store.sim_id,
        )[0]
        assert count == 2

    def test_write_mass_balance(self, runs):
        store = runs.open()
        store.write_mass_balance(store.sim_id, 0, 100.0, 95.0, 5.0)
        store.write_mass_balance(store.sim_id, 1, 110.0, 108.0, 1.8)
        rows = (
            runs.catalog()
            .connection.execute(
                "SELECT timestep, percent_error FROM mass_balance "
                "WHERE CAST(sim_id AS VARCHAR) = ? ORDER BY timestep",
                [store.sim_id],
            )
            .fetchall()
        )
        assert len(rows) == 2
        assert rows[0] == (0, 5.0)

    def test_write_mass_balance_separates_water_and_solute(self, runs):
        store = runs.open()
        store.write_mass_balances(store.sim_id, [{"timestep": 0, "percent_error": 1.0}])
        store.write_mass_balances(
            store.sim_id,
            [{"timestep": 0, "percent_error": 2.0, "quantity": "solute", "unit": "kg/s"}],
        )
        rows = (
            runs.catalog()
            .connection.execute(
                "SELECT quantity, unit, percent_error FROM mass_balance "
                "WHERE CAST(sim_id AS VARCHAR) = ? ORDER BY quantity",
                [store.sim_id],
            )
            .fetchall()
        )
        # Both budgets coexist on the same (sim_id, timestep); no collision.
        assert rows == [("solute", "kg s-1", 2.0), ("water", "m3 s-1", 1.0)]

    def test_update_simulation_grid_metadata_backfills_nulls(self, runs):
        store = runs.open()
        store.update_simulation_grid_metadata(
            store.sim_id,
            n_cells=3600,
            n_layers=2,
            mesh_hash="abc123",
            mesh_topology="structured_3d",
            bbox=[10.0, 20.0, 110.0, 220.0],
        )
        # A later update with None keeps the values already recorded.
        store.update_simulation_grid_metadata(store.sim_id, n_cells=None, mesh_hash=None)
        row = _one(
            runs.catalog(),
            "SELECT s.n_cells, s.n_layers, s.mesh_hash, mt.code, s.bbox_xmin, s.bbox_ymax "
            "FROM simulations s LEFT JOIN mesh_topologies mt ON mt.id = s.mesh_topology_id "
            "WHERE CAST(s.sim_id AS VARCHAR) = ?",
            store.sim_id,
        )
        assert row == (3600, 2, "abc123", "structured_3d", 10.0, 220.0)

    def test_write_metric_upsert(self, runs):
        store = runs.open()
        write_plain_metric(store, "P01", "nse", 0.7)
        write_plain_metric(store, "P01", "nse", 0.85)
        rows = (
            runs.catalog()
            .connection.execute(
                "SELECT value FROM metrics WHERE CAST(sim_id AS VARCHAR) = ? AND metric = 'nse'",
                [store.sim_id],
            )
            .fetchall()
        )
        assert len(rows) == 1
        assert rows[0][0] == pytest.approx(0.85)
