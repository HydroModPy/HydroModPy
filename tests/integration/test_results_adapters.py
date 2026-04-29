"""Tests for simulation/results/adapters/ - output adapters."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pandas as pd
import pytest

from hydromodpy.results.catalog import SimulationCatalog
from hydromodpy.simulation.extraction.extractors.derived import compute_derived
from hydromodpy.solver.base.cleanup import cleanup_solver_files
from hydromodpy.solver.gr4j.extractors import GR4JOutputAdapter


@pytest.fixture
def catalog(tmp_path):
    c = SimulationCatalog(tmp_path / "workspace")
    yield c
    c.close()


class TestGR4JOutputAdapter:
    def test_discharge_stored(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")

        idx = pd.date_range("2020-01-01", periods=30, freq="D")
        q = pd.Series(np.random.default_rng(1).random(30), index=idx, name="Q")

        adapter = GR4JOutputAdapter()
        adapter.extract_from_memory(sid, catalog, discharge=q)

        result = catalog.query_timeseries(sid, "outlet", "discharge")
        assert len(result) == 30
        np.testing.assert_array_almost_equal(result.values, q.values)

    def test_extra_series(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")

        idx = pd.date_range("2020-01-01", periods=10, freq="D")
        adapter = GR4JOutputAdapter()
        adapter.extract_from_memory(
            sid,
            catalog,
            extra={"evap": pd.Series(range(10), index=idx, dtype=float)},
            station_id="BV1",
        )

        result = catalog.query_timeseries(sid, "BV1", "evap")
        assert len(result) == 10

    def test_derive_noop(self, catalog):
        sid = str(uuid4())
        catalog.register_simulation(sid, project="test", solver="gr4j")
        adapter = GR4JOutputAdapter()
        adapter.derive(sid, catalog)  # should not raise


class TestDerivedVariables:
    def _setup_sim_with_head(self, catalog, n_ts=3, n_layers=2, n_cells=10):
        sid = str(uuid4())
        reg = catalog.register_simulation(
            sid,
            project="test",
            solver="modflownwt",
            n_cells=n_cells,
            n_layers=n_layers,
            n_timesteps=n_ts,
        )
        if reg.zarr is not None:
            reg.zarr.close()
        verts = np.random.default_rng(0).random((n_cells + 2, 2))
        conn = np.column_stack(
            [
                np.arange(n_cells),
                np.arange(1, n_cells + 1),
                np.full(n_cells, n_cells + 1),
            ]
        ).astype("int32")
        z_intf = np.array([10.0, 5.0, 0.0])  # top=10, mid=5, bot=0
        catalog.write_mesh(sid, verts, conn, z_intf)

        rng = np.random.default_rng(42)
        for t in range(n_ts):
            # Head values between 8 and 12 (some above surface at 10)
            head = rng.uniform(8.0, 12.0, (n_layers, n_cells))
            catalog.write_field(sid, "head", t, head, n_timesteps=n_ts if t == 0 else None)

        return sid

    def test_watertable_elevation(self, catalog):
        sid = self._setup_sim_with_head(catalog)
        compute_derived(
            sid,
            catalog,
            {"watertable_elevation": True, "watertable_depth": False, "seepage_areas": False},
        )

        wt = catalog.query_field(sid, "watertable_elevation", 0)
        assert wt.shape == (10,)

    def test_watertable_depth(self, catalog):
        sid = self._setup_sim_with_head(catalog)
        compute_derived(
            sid,
            catalog,
            {"watertable_elevation": True, "watertable_depth": True, "seepage_areas": False},
        )

        depth = catalog.query_field(sid, "watertable_depth", 0)
        assert depth.shape == (10,)
        # top=10, head~8-12, so depth = 10 - wt should be roughly -2 to 2
        assert np.all(np.isfinite(depth))

    def test_seepage_areas(self, catalog):
        sid = self._setup_sim_with_head(catalog)
        compute_derived(
            sid,
            catalog,
            {"watertable_elevation": True, "watertable_depth": False, "seepage_areas": True},
        )

        seep = catalog.query_field(sid, "seepage_areas", 0)
        assert seep.shape == (10,)
        # Some cells have head > 10 (surface), so seepage > 0
        assert seep.sum() > 0


class TestCleanupSolverFiles:
    def test_remove_all(self, tmp_path):
        d = tmp_path / "solver_output"
        d.mkdir()
        (d / "model.hds").write_text("head data")
        (d / "model.cbc").write_text("budget data")
        (d / "model.lst").write_text("listing")

        cleanup_solver_files(d)
        assert not d.exists()

    def test_keep_extensions(self, tmp_path):
        d = tmp_path / "solver_output"
        d.mkdir()
        (d / "model.hds").write_text("head data")
        (d / "model.lst").write_text("listing")
        (d / "model.nam").write_text("name file")

        cleanup_solver_files(d, keep={".lst", ".nam"})
        assert (d / "model.lst").exists()
        assert (d / "model.nam").exists()
        assert not (d / "model.hds").exists()
