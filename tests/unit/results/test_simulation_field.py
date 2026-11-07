from __future__ import annotations

import numpy as np

from hydromodpy.results.run import Run
from tests._helpers.run_builders import runs

__all__ = ["runs"]


class TestSimulationField:
    def test_read_field(self, runs):
        store = runs.open(n_cells=20, n_layers=2, n_timesteps=3)
        sid = store.sim_id
        for t in range(3):
            store.write_field(sid, "head", t, np.ones((2, 20)), n_timesteps=3 if t == 0 else None)
        result = Run(sid, runs.catalog()).field("head", time=1)
        assert result.shape == (2, 20)

    def test_negative_timestep(self, runs):
        store = runs.open(n_cells=5, n_layers=1, n_timesteps=4)
        sid = store.sim_id
        for t in range(4):
            store.write_field(
                sid, "head", t, np.full(5, float(t)), n_timesteps=4 if t == 0 else None
            )
        result = Run(sid, runs.catalog()).field("head", time=-1)
        np.testing.assert_array_equal(result, np.full(5, 3.0))
