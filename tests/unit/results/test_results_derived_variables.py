"""The water table elevation (m) is rebuilt on read from the stored head."""

from __future__ import annotations

import numpy as np

from tests._helpers.run_builders import runs

__all__ = ["runs"]


def test_watertable_elevation(runs):
    n_cells, n_layers, n_steps = 10, 2, 3
    sid = runs.open(
        solver="modflow_nwt", n_cells=n_cells, n_layers=n_layers, n_timesteps=n_steps
    ).sim_id
    vertices = np.random.default_rng(0).random((n_cells + 2, 2))
    connectivity = np.column_stack(
        [np.arange(n_cells), np.arange(1, n_cells + 1), np.full(n_cells, n_cells + 1)]
    ).astype("int32")
    interfaces = np.array([10.0, 5.0, 0.0])  # top 10 m, middle 5 m, bottom 0 m
    runs.store(sid).write_mesh(sid, vertices, connectivity, interfaces)
    rng = np.random.default_rng(42)
    for step in range(n_steps):
        # Heads between 8 and 12 m, some above the surface at 10 m.
        head = rng.uniform(8.0, 12.0, (n_layers, n_cells))
        runs.store(sid).write_field(
            sid, "head", step, head, n_timesteps=n_steps if step == 0 else None
        )

    water_table = runs.reader().query_field(sid, "watertable_elevation", 0)

    assert water_table.shape == (n_cells,)
