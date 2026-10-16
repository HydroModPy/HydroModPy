"""The water table and the seepage mask are rebuilt on read from the stored head."""

from __future__ import annotations

import numpy as np
import pytest

from ._test_simulation_api_builders import RunBuilder, runs

__all__ = ["runs"]


class TestVariablesRebuiltOnRead:
    def _setup_sim_with_head(self, runs, n_ts=3, n_layers=2, n_cells=10):
        sid = runs.open(
            solver="modflow_nwt", n_cells=n_cells, n_layers=n_layers, n_timesteps=n_ts
        ).sim_id
        verts = np.random.default_rng(0).random((n_cells + 2, 2))
        conn = np.column_stack(
            [
                np.arange(n_cells),
                np.arange(1, n_cells + 1),
                np.full(n_cells, n_cells + 1),
            ]
        ).astype("int32")
        z_intf = np.array([10.0, 5.0, 0.0])  # top=10, mid=5, bot=0
        runs.store(sid).write_mesh(sid, verts, conn, z_intf)

        rng = np.random.default_rng(42)
        for t in range(n_ts):
            # Head values between 8 and 12 (some above surface at 10)
            head = rng.uniform(8.0, 12.0, (n_layers, n_cells))
            runs.store(sid).write_field(sid, "head", t, head, n_timesteps=n_ts if t == 0 else None)

        return sid

    def test_watertable_elevation(self, runs):
        sid = self._setup_sim_with_head(runs)
        wt = runs.reader().query_field(sid, "watertable_elevation", 0)
        assert wt.shape == (10,)

    def test_watertable_depth(self, runs):
        sid = self._setup_sim_with_head(runs)
        depth = runs.reader().query_field(sid, "watertable_depth", 0)
        assert depth.shape == (10,)
        # top=10, head~8-12, so depth = 10 - wt should be roughly -2 to 2
        assert np.all(np.isfinite(depth))

    def test_seepage_mask(self, runs):
        sid = self._setup_sim_with_head(runs)
        seep = runs.reader().query_field(sid, "seepage_mask", 0)
        assert seep.shape == (10,)
        # Some cells have head > 10 (surface), so seepage > 0
        assert seep.sum() > 0
