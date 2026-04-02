"""Tests for simulation/results/store.py — ResultStore integration."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.simulation.results.store import ResultStore


@pytest.fixture
def store(tmp_path):
    project = tmp_path / "projects" / "test_project"
    workspace = tmp_path / "workspace"
    s = ResultStore(project, workspace)
    yield s
    s.close()


@pytest.fixture
def store_no_workspace(tmp_path):
    project = tmp_path / "projects" / "solo"
    s = ResultStore(project)
    yield s
    s.close()


def _make_mesh():
    """Simple 4-triangle mesh for testing."""
    vertices = np.array([
        [0.0, 0.0], [2.0, 0.0], [1.0, 1.0], [0.0, 2.0], [2.0, 2.0],
    ])
    connectivity = np.array([
        [0, 1, 2], [1, 4, 2], [2, 4, 3], [0, 2, 3],
    ], dtype="int32")
    z_interfaces = np.array([0.0, -5.0, -15.0])
    return vertices, connectivity, z_interfaces


class TestFullCycle:
    """register → write_mesh → write_field → finalize → query_field"""

    def test_field_roundtrip(self, store):
        sid = str(uuid4())
        n_cells, n_layers, n_ts = 4, 2, 5
        verts, conn, z = _make_mesh()

        store.register_simulation(
            sid, name="test_run", solver="modflownwt",
            n_cells=n_cells, n_layers=n_layers, n_timesteps=n_ts,
        )
        store.write_mesh(sid, verts, conn, z)

        rng = np.random.default_rng(42)
        all_vals = rng.random((n_ts, n_layers, n_cells))
        for t in range(n_ts):
            store.write_field(sid, "head", t, all_vals[t], n_timesteps=n_ts if t == 0 else None)

        store.finalize(sid, status="completed", duration_s=12.5)

        result = store.query_field(sid, "head", 2)
        np.testing.assert_array_almost_equal(result, all_vals[2])

        result_layer = store.query_field(sid, "head", 2, layer=0)
        np.testing.assert_array_almost_equal(result_layer, all_vals[2, 0])

    def test_list_simulations(self, store):
        sid = str(uuid4())
        store.register_simulation(sid, name="run_A", solver="modflow6")
        store.finalize(sid, status="completed")

        df = store.list_simulations()
        assert len(df) == 1
        assert df.iloc[0]["name"] == "run_A"

        df_f = store.list_simulations(solver="gr4j")
        assert len(df_f) == 0


class TestTimeseriesCycle:
    """register → write_timeseries → query_timeseries"""

    def test_roundtrip(self, store):
        sid = str(uuid4())
        store.register_simulation(sid, solver="gr4j")

        idx = pd.date_range("2020-01-01", periods=30, freq="D")
        ts = pd.Series(np.random.default_rng(7).random(30), index=idx, name="discharge")
        store.write_timeseries(sid, "EXU", "discharge", ts, unit="m3/s")

        result = store.query_timeseries(sid, "EXU", "discharge")
        assert len(result) == 30
        np.testing.assert_array_almost_equal(result.values, ts.values)

    def test_period_filter(self, store):
        sid = str(uuid4())
        store.register_simulation(sid, solver="gr4j")

        idx = pd.date_range("2020-01-01", periods=30, freq="D")
        ts = pd.Series(range(30), index=idx, dtype=float)
        store.write_timeseries(sid, "S1", "head", ts)

        result = store.query_timeseries(
            sid, "S1", "head", period=("2020-01-10", "2020-01-20"),
        )
        assert len(result) == 11


class TestBudgetAndMassBalance:
    def test_budget_roundtrip(self, store):
        sid = str(uuid4())
        store.register_simulation(sid, solver="modflownwt")

        for t in range(5):
            store.write_budget(sid, t, 0, "recharge", 100.0 + t, 0.0)
            store.write_budget(sid, t, 0, "drain", 0.0, 80.0 + t)

        df = store.query_budget(sid)
        assert len(df) == 10

        df_zone = store.query_budget(sid, zone_id=0, period=(1, 3))
        assert len(df_zone) == 6

    def test_mass_balance_roundtrip(self, store):
        sid = str(uuid4())
        store.register_simulation(sid, solver="modflownwt")

        for t in range(3):
            store.write_mass_balance(sid, t, 1000.0, 995.0, 0.5)

        df = store.query_mass_balance(sid)
        assert len(df) == 3
        assert df.iloc[0]["percent_error"] == pytest.approx(0.5)


class TestProvenance:
    def test_roundtrip_and_verify(self, store):
        sid = str(uuid4())
        store.register_simulation(sid, solver="modflownwt")

        data = np.random.default_rng(99).random((365, 100))
        store.record_provenance(sid, "recharge", "recharge/sim2", data)

        df = store.get_provenance(sid, "recharge")
        assert len(df) == 1
        assert df.iloc[0]["source_ref"] == "recharge/sim2"

        assert store.verify_provenance(sid, "recharge", data)

        altered = data.copy()
        altered[0, 0] += 0.001
        assert not store.verify_provenance(sid, "recharge", altered)


class TestDeleteSimulation:
    def test_cleans_all_stores(self, store):
        sid = str(uuid4())
        store.register_simulation(
            sid, solver="modflownwt", n_cells=4, n_layers=2, n_timesteps=1,
        )
        verts, conn, z = _make_mesh()
        store.write_mesh(sid, verts, conn, z)
        store.write_field(sid, "head", 0, np.zeros((2, 4)), n_timesteps=1)
        store.finalize(sid, status="completed")

        store.delete_simulation(sid)

        assert len(store.list_simulations()) == 0

        import zarr
        root = zarr.open_group(store._zarr_path, mode="r")
        assert str(sid) not in root


class TestCompare:
    def test_diff_stats(self, store):
        sid_a = str(uuid4())
        sid_b = str(uuid4())
        n_cells, n_layers = 10, 1

        for sid in (sid_a, sid_b):
            store.register_simulation(
                sid, solver="test", n_cells=n_cells, n_layers=n_layers, n_timesteps=1,
            )

        vals_a = np.ones((n_layers, n_cells))
        vals_b = np.ones((n_layers, n_cells)) * 2.0
        store.write_field(sid_a, "head", 0, vals_a, n_timesteps=1)
        store.write_field(sid_b, "head", 0, vals_b, n_timesteps=1)

        diff = store.compare(sid_a, sid_b, "head", 0)
        assert diff["mean_diff"] == pytest.approx(-1.0)
        assert diff["rmse"] == pytest.approx(1.0)


class TestNoWorkspace:
    def test_works_without_workspace(self, store_no_workspace):
        sid = str(uuid4())
        store_no_workspace.register_simulation(sid, solver="gr4j")
        store_no_workspace.finalize(sid, status="completed")
        df = store_no_workspace.list_simulations()
        assert len(df) == 1
