from __future__ import annotations

import numpy as np

from hydromodpy.results.run import Run

from ._test_simulation_api_builders import _register, catalog

__all__ = ["catalog"]


class TestSimulationField:
    def test_read_field(self, catalog):
        sid = _register(catalog, n_cells=20, n_layers=2, n_timesteps=3)
        sz = catalog.open_zarr(sid)
        for t in range(3):
            sz.write_field("head", t, np.ones((2, 20)), n_timesteps=3 if t == 0 else None)
        sim = Run(sid, catalog)
        result = sim.field("head", timestep=1)
        assert result.shape == (2, 20)

    def test_negative_timestep(self, catalog):
        sid = _register(catalog, n_cells=5, n_layers=1, n_timesteps=4)
        sz = catalog.open_zarr(sid)
        for t in range(4):
            vals = np.full(5, float(t))
            sz.write_field("head", t, vals, n_timesteps=4 if t == 0 else None)
        sim = Run(sid, catalog)
        result = sim.field("head", timestep=-1)
        np.testing.assert_array_equal(result, np.full(5, 3.0))
