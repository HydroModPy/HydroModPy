"""Unit tests for derived-variable computation (watertable, seepage)."""

from __future__ import annotations

from uuid import uuid4

import numpy as np
import pytest

from hydromodpy.simulation.extraction.derivation.derived import compute_derived
from tests._helpers.fixtures_catalog import simulation_catalog


@pytest.fixture
def catalog(tmp_path):
    with simulation_catalog(tmp_path / "workspace") as cat:
        yield cat


class TestDerivedVariables:
    def _setup_sim_with_head(self, catalog, n_ts=3, n_layers=2, n_cells=10):
        sid = str(uuid4())
        reg = catalog.register_simulation(
            sid,
            project="test",
            solver="modflow_nwt",
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

    def test_seepage_mask(self, catalog):
        sid = self._setup_sim_with_head(catalog)
        compute_derived(
            sid,
            catalog,
            {"watertable_elevation": True, "watertable_depth": False, "seepage_areas": True},
        )

        seep = catalog.query_field(sid, "seepage_mask", 0)
        assert seep.shape == (10,)
        # Some cells have head > 10 (surface), so seepage > 0
        assert seep.sum() > 0
