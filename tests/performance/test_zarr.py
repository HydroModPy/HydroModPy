"""Field write/read baseline benchmarks (SimulationCatalog Zarr backend).

Guards the thin HydroModPy field-array wrapper (``write_field`` /
``query_field``) backed by Zarr that the solver extraction layer calls per
timestep. A regression in the Zarr field round-trip shows up here as a
pairwise-ratio drift in ``perf.yml``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests._helpers.fixtures_catalog import simulation_catalog

pytestmark = pytest.mark.performance

GRID = (100, 100)
N_TIME = 10
SID = "00000000-0000-0000-0000-0000000000a1"


@pytest.fixture(scope="function")
def field_catalog(tmp_path: Path):
    """Catalog holding one simulation with a 10x100x100 head field."""
    rng = np.random.default_rng(seed=42)
    with simulation_catalog(tmp_path / "workspace") as cat:
        reg = cat.register_simulation(SID, project="perf", solver="modflow6")
        if reg.zarr is not None:
            reg.zarr.close()
        for t in range(N_TIME):
            cat.write_field(
                SID, "head", t, rng.random(GRID), n_timesteps=N_TIME if t == 0 else None
            )
        yield cat


@pytest.mark.benchmark(group="zarr")
def test_zarr_write_field(benchmark, field_catalog) -> None:
    """Overwrite one field timestep slice (100x100) via the catalog wrapper."""
    arr = np.random.default_rng(seed=0).random(GRID)

    def _write() -> None:
        field_catalog.write_field(SID, "head", 0, arr)

    benchmark(_write)


@pytest.mark.benchmark(group="zarr")
def test_zarr_read_field(benchmark, field_catalog) -> None:
    """Read one field timestep slice (100x100) via the catalog wrapper."""

    def _read() -> np.ndarray:
        return field_catalog.query_field(SID, "head", 0)

    benchmark(_read)
