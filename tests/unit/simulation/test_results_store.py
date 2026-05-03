"""Tests for results/catalog.py - SimulationCatalog integration."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.array_fingerprint import fingerprint
from hydromodpy.results.catalog import SimulationCatalog


@pytest.fixture
def catalog(tmp_path):
    c = SimulationCatalog(tmp_path / "workspace")
    yield c
    c.close()


def _make_mesh():
    """Simple 4-triangle mesh for testing."""
    vertices = np.array(
        [
            [0.0, 0.0],
            [2.0, 0.0],
            [1.0, 1.0],
            [0.0, 2.0],
            [2.0, 2.0],
        ]
    )
    connectivity = np.array(
        [
            [0, 1, 2],
            [1, 4, 2],
            [2, 4, 3],
            [0, 2, 3],
        ],
        dtype="int32",
    )
    z_interfaces = np.array([0.0, -5.0, -15.0])
    return vertices, connectivity, z_interfaces


class TestFullCycle:
    """register → write_mesh → write_field → finalize → query_field"""

    def test_field_roundtrip(self, catalog):
        sid = str(uuid4())
        n_cells, n_layers, n_ts = 4, 2, 5
        verts, conn, z = _make_mesh()

        reg = catalog.register_simulation(
            sid,
            project="test",
            solver="modflownwt",
            name="test_run",
            n_cells=n_cells,
            n_layers=n_layers,
            n_timesteps=n_ts,
        )
        if reg.zarr is not None:
            reg.zarr.close()
        catalog.write_mesh(sid, verts, conn, z)

        rng = np.random.default_rng(42)
        all_vals = rng.random((n_ts, n_layers, n_cells))
        for t in range(n_ts):
            catalog.write_field(sid, "head", t, all_vals[t], n_timesteps=n_ts if t == 0 else None)

        catalog.finalize(sid, status="completed", duration_s=12.5)

        result = catalog.query_field(sid, "head", 2)
        np.testing.assert_array_almost_equal(result, all_vals[2])

        result_layer = catalog.query_field(sid, "head", 2, layer=0)
        np.testing.assert_array_almost_equal(result_layer, all_vals[2, 0])

    def test_finalize_flushes_open_zarr_handles(self, catalog):
        sid = str(uuid4())
        reg = catalog.register_simulation(
            sid,
            project="test",
            solver="boussinesq",
            name="open_handles",
            n_cells=4,
            n_layers=1,
            n_timesteps=1,
        )
        assert reg.zarr is not None

        sz = catalog.open_zarr(sid)
        mesh = sz.root["mesh"]
        mesh.create_array("surface_top", data=np.array([10.0, 10.0, 10.0, 10.0]), overwrite=True)

        values = np.array([[1.0, 2.0, 3.0, 4.0]], dtype="float64")
        catalog.write_field(sid, "head", 0, values, n_timesteps=1)

        catalog.finalize(sid, status="completed", duration_s=1.0)

        zarr_path = catalog.zarr_path_for(sid)
        assert zarr_path.suffix == ".zip"

        sz = catalog.open_zarr(sid)
        try:
            np.testing.assert_array_equal(
                sz.root["mesh"]["surface_top"][:],
                [10.0, 10.0, 10.0, 10.0],
            )
            np.testing.assert_array_equal(sz.read_field("head", 0), values)
        finally:
            sz.close()

    def test_transient_zarr_handles_are_untracked_after_close(self, catalog):
        sid = str(uuid4())
        reg = catalog.register_simulation(
            sid,
            project="test",
            solver="modflownwt",
            name="transient_handles",
            n_cells=4,
            n_layers=2,
            n_timesteps=1,
        )
        assert reg.zarr is not None
        assert len(catalog._open_zarr_handles) == 1

        reg.zarr.close()
        assert catalog._open_zarr_handles == []

        verts, conn, z = _make_mesh()
        catalog.write_mesh(sid, verts, conn, z)
        assert catalog._open_zarr_handles == []

        values = np.ones((2, 4), dtype="float64")
        catalog.write_field(sid, "head", 0, values, n_timesteps=1)
        assert catalog._open_zarr_handles == []

        result = catalog.query_field(sid, "head", 0)
        np.testing.assert_array_equal(result, values)
        assert catalog._open_zarr_handles == []

    def test_list_simulations(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflow6", name="run_A")
        catalog.finalize(sid, status="completed")

        df = catalog.list_simulations()
        assert len(df) == 1
        assert df.iloc[0]["name"] == "run_A"

        df_f = catalog.list_simulations(solver="gr4j")
        assert len(df_f) == 0


class TestTimeseriesCycle:
    """register → write_timeseries → query_timeseries"""

    def test_roundtrip(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")

        idx = pd.date_range("2020-01-01", periods=30, freq="D")
        ts = pd.Series(np.random.default_rng(7).random(30), index=idx, name="discharge")
        catalog.write_timeseries(sid, "EXU", "discharge", ts, unit="m3/s")

        result = catalog.query_timeseries(sid, "EXU", "discharge")
        assert len(result) == 30
        np.testing.assert_array_almost_equal(result.values, ts.values)

    def test_period_filter(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")

        idx = pd.date_range("2020-01-01", periods=30, freq="D")
        ts = pd.Series(range(30), index=idx, dtype=float)
        catalog.write_timeseries(sid, "S1", "head", ts)

        result = catalog.query_timeseries(
            sid,
            "S1",
            "head",
            period=("2020-01-10", "2020-01-20"),
        )
        assert len(result) == 11


class TestBudgetAndMassBalance:
    def test_budget_roundtrip(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")

        for t in range(5):
            catalog.write_budget(sid, t, "0", "recharge", 100.0 + t, 0.0)
            catalog.write_budget(sid, t, "0", "drain", 0.0, 80.0 + t)

        df = catalog.query_budget(sid)
        assert len(df) == 10

        df_zone = catalog.query_budget(sid, zone_id="0", period=(1, 3))
        assert len(df_zone) == 6

    def test_mass_balance_roundtrip(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")

        for t in range(3):
            catalog.write_mass_balance(sid, t, 1000.0, 995.0, 0.5)

        df = catalog.query_mass_balance(sid)
        assert len(df) == 3
        assert df.iloc[0]["percent_error"] == pytest.approx(0.5)


class TestProvenance:
    def test_roundtrip_and_verify(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="modflownwt")

        data = np.random.default_rng(99).random((365, 100))
        catalog.write_provenance(sid, "recharge", "recharge/sim2", data)

        df = catalog.get_provenance(sid, "recharge")
        assert len(df) == 1
        assert df.iloc[0]["source_ref"] == "recharge/sim2"

        # Verify provenance via fingerprint comparison
        stored_checksum = df.iloc[0]["payload_sha256"]
        assert fingerprint(data)["checksum"] == stored_checksum

        altered = data.copy()
        altered[0, 0] += 0.001
        assert fingerprint(altered)["checksum"] != stored_checksum


class TestDeleteSimulation:
    def test_cleans_all_stores(self, catalog):
        sid = str(uuid4())
        reg = catalog.register_simulation(
            sid,
            project="test",
            solver="modflownwt",
            n_cells=4,
            n_layers=2,
            n_timesteps=1,
        )
        if reg.zarr is not None:
            reg.zarr.close()
        verts, conn, z = _make_mesh()
        catalog.write_mesh(sid, verts, conn, z)
        catalog.write_field(sid, "head", 0, np.zeros((2, 4)), n_timesteps=1)
        catalog.finalize(sid, status="completed")

        zarr_zip = catalog.zarr_path_for(sid)
        assert zarr_zip.exists()
        assert zarr_zip.suffix == ".zip"

        catalog.delete(sid)

        assert len(catalog.list_simulations()) == 0
        assert not zarr_zip.exists()


class TestCompare:
    def test_diff_stats(self, catalog):
        sid_a = str(uuid4())
        sid_b = str(uuid4())
        n_cells, n_layers = 10, 1

        for sid in (sid_a, sid_b):
            reg = catalog.register_simulation(
                sid,
                project="test",
                solver="test",
                n_cells=n_cells,
                n_layers=n_layers,
                n_timesteps=1,
            )
            if reg.zarr is not None:
                reg.zarr.close()

        vals_a = np.ones((n_layers, n_cells))
        vals_b = np.ones((n_layers, n_cells)) * 2.0
        catalog.write_field(sid_a, "head", 0, vals_a, n_timesteps=1)
        catalog.write_field(sid_b, "head", 0, vals_b, n_timesteps=1)

        arr_a = catalog.query_field(sid_a, "head", 0).ravel()
        arr_b = catalog.query_field(sid_b, "head", 0).ravel()
        diff = arr_a - arr_b
        mean_diff = float(diff.mean())
        rmse = float(np.sqrt((diff**2).mean()))

        assert mean_diff == pytest.approx(-1.0)
        assert rmse == pytest.approx(1.0)
