"""Field write/read baseline benchmarks (run store Zarr backend).

Guards the thin HydroModPy field-array wrapper (``write_field`` /
``query_field``) of the run store, backed by Zarr, that the solver extraction
layer calls per timestep. A regression in the Zarr field round-trip shows up
here as a pairwise-ratio drift in ``perf.yml``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests._helpers.run_stores import open_run_store

pytestmark = pytest.mark.performance

GRID = (100, 100)
N_TIME = 10


@pytest.fixture(scope="function")
def field_store(tmp_path: Path):
    """Store of one run with a 10x100x100 head field."""
    rng = np.random.default_rng(seed=42)
    n_layers, n_cells = GRID
    with open_run_store(
        tmp_path / "project", "perf", n_cells=n_cells, n_layers=n_layers, n_timesteps=N_TIME
    ) as store:
        for t in range(N_TIME):
            store.write_field(
                store.sim_id, "head", t, rng.random(GRID), n_timesteps=N_TIME if t == 0 else None
            )
        yield store


@pytest.mark.benchmark(group="zarr")
def test_zarr_write_field(benchmark, field_store) -> None:
    """Overwrite one field timestep slice (100x100) via the run store wrapper."""
    arr = np.random.default_rng(seed=0).random(GRID)

    def _write() -> None:
        field_store.write_field(field_store.sim_id, "head", 0, arr)

    benchmark(_write)


@pytest.mark.benchmark(group="zarr")
def test_zarr_read_field(benchmark, field_store) -> None:
    """Read one field timestep slice (100x100) via the run store wrapper."""

    def _read() -> np.ndarray:
        return field_store.query_field(field_store.sim_id, "head", 0)

    benchmark(_read)
