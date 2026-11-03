"""A run writes its own directory; the index states what the sealed directories hold."""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import Catalog
from hydromodpy.results.catalog.constants import GLOBAL_ZONE
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.lineage import Lineage
from hydromodpy.results.storage.contract import RUN_MANIFEST_FILENAME

from ._test_simulation_api_builders import runs, write_plain_metric

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


def test_zarr_is_created_at_its_final_path_without_staging(runs):
    """The store is written where readers expect it: no staging, no promotion."""
    store = runs.open("direct_write", n_cells=8, n_layers=1)
    fields_path = store.fields_path

    assert fields_path.is_dir()
    assert fields_path.parent == store.run_dir
    assert not any(child.name.startswith(".staging") for child in store.run_dir.iterdir())

    catalog = runs.catalog()
    assert catalog.fields_path_for(store.sim_id) == fields_path
    assert fields_path.is_dir()


class TestSealAndIndex:
    def test_a_sealed_run_is_indexed_completed(self, runs):
        sid = runs.open(project="test_project").sim_id
        row = _one(runs.catalog(), _SIM_SELECT, sid)
        assert row[:3] == ("test_project", "modflow6", "completed")

    def test_the_field_store_holds_the_mesh_of_the_grid(self, runs):
        store = runs.open(n_cells=50, n_layers=2)
        handle = store.open_zarr(store.sim_id)
        try:
            assert "mesh" in handle.root
        finally:
            handle.close()

    def test_a_run_without_fields_writes_no_field_store(self, runs):
        store = runs.open(create_zarr=False)
        assert not store.fields_path.exists()

    def test_solver_category_auto_distributed(self, runs):
        sid = runs.open(solver="modflow_nwt").sim_id
        assert _one(runs.catalog(), _SIM_SELECT, sid)[3] == "distributed"

    def test_solver_category_auto_integrated(self, runs):
        sid = runs.open(solver="boussinesq").sim_id
        assert _one(runs.catalog(), _SIM_SELECT, sid)[3] == "integrated"

    def test_a_run_of_an_unknown_solver_is_skipped_by_name(self, runs):
        store = runs.open(solver="exotic_solver")
        runs.seal(store)

        report = rebuild_index(runs.project_root)

        assert [entry.rel_dir for entry in report.skipped] == [f"runs/{store.run_dir.name}"]
        assert "exotic_solver" in report.skipped[0].reason

    def test_the_duration_is_the_measured_interval(self, runs):
        """The sealed row states how long the run really took.

        Measuring an interval this test controls is the only way to tell a
        derived duration from a stored one.
        """
        store = runs.open()
        time.sleep(0.25)
        before = time.monotonic()
        runs.seal(store)
        sealing = time.monotonic() - before

        row = _one(runs.catalog(), _SIM_SELECT, store.sim_id)
        assert row[2] == "completed"
        assert 0.25 <= row[4] <= 0.25 + sealing + 1.0

    def test_a_taken_name_gets_the_next_version(self, runs):
        """The bare name is version 1 for good: ``r1``, ``r1.v2``, ``r1.v3``."""
        first = runs.open("r1").sim_id
        runs.catalog()
        runs.open("r1")
        runs.catalog()
        third = runs.open("r1").sim_id
        catalog = runs.catalog()

        names = {
            r[0] for r in catalog.connection.execute("SELECT name FROM simulations").fetchall()
        }
        assert names == {"r1", "r1.v2", "r1.v3"}
        assert _one(
            catalog,
            "SELECT name, version_int FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?",
            first,
        ) == ("r1", 1)
        assert _one(
            catalog, "SELECT name FROM simulations WHERE CAST(sim_id AS VARCHAR) = ?", third
        ) == ("r1.v3",)

    def test_a_second_run_leaves_the_first_sealed_directory_untouched(self, runs):
        first = runs.open("r1")
        runs.catalog()
        manifest = first.run_dir / RUN_MANIFEST_FILENAME
        before = manifest.read_bytes()

        runs.open("r1")
        runs.catalog()

        assert manifest.read_bytes() == before

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
    def test_write_parameters_bulk(self, runs):
        store = runs.open()
        store.write_parameters(
            store.sim_id,
            [
                {
                    "param_name": "K",
                    "value": 1.728,
                    "unit": "m/d",
                    "parameterization": "homogeneous",
                },
                {"param_name": "Sy", "value": 0.05, "unit": "-", "parameterization": "homogeneous"},
                {
                    "param_name": "K",
                    "zone_id": "granite",
                    "value": 0.5,
                    "unit": "m/d",
                    "parameterization": "geology_mapped",
                },
            ],
        )
        count = _one(
            runs.catalog(),
            "SELECT COUNT(*) FROM parameters WHERE CAST(sim_id AS VARCHAR) = ?",
            store.sim_id,
        )[0]
        assert count == 3

    def test_parameters_global_zone_default(self, runs):
        store = runs.open()
        store.write_parameters(store.sim_id, [{"param_name": "K", "value": 1.0}])
        row = _one(
            runs.catalog(),
            "SELECT zone_id FROM parameters WHERE CAST(sim_id AS VARCHAR) = ? AND param_name = 'K'",
            store.sim_id,
        )
        assert row[0] == GLOBAL_ZONE

    def test_write_timeseries(self, runs):
        store = runs.open()
        idx = pd.date_range("2020-01-01", periods=30, freq="D")
        series = pd.Series(np.arange(30, dtype="float64"), index=idx, name="head")
        store.write_timeseries(store.sim_id, "P01", "head", series, unit="m")
        count = _one(
            runs.catalog(),
            "SELECT COUNT(*) FROM timeseries WHERE CAST(sim_id AS VARCHAR) = ?",
            store.sim_id,
        )[0]
        assert count == 30

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
        assert rows == [("solute", "kg/s", 2.0), ("water", "m3/s", 1.0)]

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
                "SELECT value FROM metrics "
                "WHERE CAST(sim_id AS VARCHAR) = ? AND metric_name = 'nse'",
                [store.sim_id],
            )
            .fetchall()
        )
        assert len(rows) == 1
        assert rows[0][0] == pytest.approx(0.85)

    def test_write_provenance(self, runs):
        store = runs.open()
        data = np.random.default_rng(0).random(100)
        store.write_provenance(store.sim_id, "recharge", "/data/recharge.nc", data)
        row = _one(
            runs.catalog(),
            "SELECT payload_sha256, n_records FROM provenance WHERE CAST(sim_id AS VARCHAR) = ?",
            store.sim_id,
        )
        assert row[0] is not None
        assert row[1] == 100


class TestContextManager:
    def test_enter_exit(self, runs):
        runs.open()
        runs.catalog()
        runs.close_catalog()
        with Catalog(runs.project_root) as cat:
            assert cat.connection.execute("SELECT COUNT(*) FROM simulations").fetchone()[0] == 1
        assert cat.closed
