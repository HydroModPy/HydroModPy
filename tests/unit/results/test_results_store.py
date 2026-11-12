"""A run written through its store and sealed reads back through the index."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.fields.precision import MAX_RELATIVE_ERROR
from hydromodpy.results.storage.array_fingerprint import fingerprint
from tests._helpers.run_builders import runs

__all__ = ["runs"]


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
    """open -> write_mesh -> write_field -> seal -> index -> query_field"""

    def test_field_roundtrip(self, runs):
        n_cells, n_layers, n_ts = 4, 2, 5
        verts, conn, z = _make_mesh()
        store = runs.open(
            "test_run", solver="modflow_nwt", n_cells=n_cells, n_layers=n_layers, n_timesteps=n_ts
        )
        sid = store.sim_id
        store.write_mesh(sid, verts, conn, z)
        rng = np.random.default_rng(42)
        all_vals = rng.random((n_ts, n_layers, n_cells))
        for t in range(n_ts):
            store.write_field(sid, "head", t, all_vals[t], n_timesteps=n_ts if t == 0 else None)

        catalog = runs.catalog()

        # Stored in the compact precision: equal within its relative bound.
        result = catalog.query_field(sid, "head", 2)
        np.testing.assert_allclose(result, all_vals[2], rtol=MAX_RELATIVE_ERROR, atol=0.0)
        result_layer = catalog.query_field(sid, "head", 2, layer=0)
        np.testing.assert_allclose(result_layer, all_vals[2, 0], rtol=MAX_RELATIVE_ERROR, atol=0.0)

    def test_list_simulations(self, runs):
        runs.open("run_a")
        df = runs.catalog().list_simulations()
        assert list(df["name"]) == ["run_a"]
        assert runs.catalog().list_simulations(solver="gr4j").empty


class TestTimeseriesCycle:
    """write_timeseries -> seal -> query_timeseries"""

    def test_roundtrip(self, runs):
        store = runs.open(solver="gr4j")
        idx = pd.date_range("2020-01-01", periods=30, freq="D")
        ts = pd.Series(np.random.default_rng(7).random(30), index=idx, name="discharge")
        store.write_timeseries(store.sim_id, "EXU", "discharge", ts, unit="m3/s")

        result = runs.catalog().query_timeseries(store.sim_id, "EXU", "discharge")
        assert len(result) == 30
        np.testing.assert_array_almost_equal(result.values, ts.values)


class TestBudgetAndMassBalance:
    def test_budget_roundtrip(self, runs):
        store = runs.open(solver="modflow_nwt")
        for t in range(5):
            store.write_budget(store.sim_id, t, "domain", "recharge", 100.0 + t, 0.0)
            store.write_budget(store.sim_id, t, "domain", "drain", 0.0, 80.0 + t)

        catalog = runs.catalog()
        assert len(catalog.query_budget(store.sim_id)) == 10
        assert len(catalog.query_budget(store.sim_id, zone_id="domain", steps=(1, 3))) == 6

    def test_mass_balance_roundtrip(self, runs):
        store = runs.open(solver="modflow_nwt")
        for t in range(3):
            store.write_mass_balance(store.sim_id, t, 1000.0, 995.0, 0.5)

        df = runs.catalog().query_mass_balance(store.sim_id)
        assert len(df) == 3
        assert df.iloc[0]["percent_error"] == pytest.approx(0.5)


class TestProvenance:
    def test_roundtrip_and_verify(self, runs):
        store = runs.open(solver="modflow_nwt")
        data = np.random.default_rng(99).random((365, 100))
        store.write_provenance(store.sim_id, "recharge", "recharge/sim2", data)

        df = runs.catalog().get_provenance(store.sim_id, "recharge")
        assert len(df) == 1
        assert df.iloc[0]["source_ref"] == "recharge/sim2"

        # Verify provenance via fingerprint comparison
        stored_checksum = df.iloc[0]["payload_sha256"]
        assert fingerprint(data)["checksum"] == stored_checksum
        altered = data.copy()
        altered[0, 0] += 0.001
        assert fingerprint(altered)["checksum"] != stored_checksum


class TestCompare:
    def test_diff_stats(self, runs):
        n_cells, n_layers = 10, 1
        first = runs.open(n_cells=n_cells, n_layers=n_layers, n_timesteps=1)
        second = runs.open(n_cells=n_cells, n_layers=n_layers, n_timesteps=1)
        first.write_field(first.sim_id, "head", 0, np.ones((n_layers, n_cells)), n_timesteps=1)
        second.write_field(
            second.sim_id, "head", 0, np.ones((n_layers, n_cells)) * 2.0, n_timesteps=1
        )

        catalog = runs.catalog()
        diff = (
            catalog.query_field(first.sim_id, "head", 0).ravel()
            - catalog.query_field(second.sim_id, "head", 0).ravel()
        )
        assert float(diff.mean()) == pytest.approx(-1.0)
        assert float(np.sqrt((diff**2).mean())) == pytest.approx(1.0)
