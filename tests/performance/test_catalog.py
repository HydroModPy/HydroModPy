"""SimulationCatalog open/list baseline benchmarks (DuckDB backend).

Guards the thin HydroModPy catalog wrapper the v2 pipeline opens on every
run: the DuckDB connection plus workspace layout, and a ``list_simulations``
query over a populated catalog. A regression in ``SimulationCatalog`` open or
query shows up here as a pairwise-ratio drift in ``perf.yml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.catalog import SimulationCatalog
from tests._helpers.fixtures_catalog import simulation_catalog

pytestmark = pytest.mark.performance

N_SIMS = 100


def _populate(workspace: Path) -> None:
    """Register ``N_SIMS`` rows in a fresh catalog under ``workspace``."""
    with simulation_catalog(workspace) as cat:
        for i in range(N_SIMS):
            sid = f"00000000-0000-0000-0000-{i:012d}"
            reg = cat.register_simulation(sid, project="perf", solver="modflow6", name=f"sim_{i}")
            if reg.zarr is not None:
                reg.zarr.close()


@pytest.fixture(scope="function")
def catalog_workspace(tmp_path: Path) -> Path:
    """Build a catalog workspace pre-populated with ``N_SIMS`` simulations."""
    workspace = tmp_path / "workspace"
    _populate(workspace)
    return workspace


@pytest.mark.benchmark(group="catalog")
def test_catalog_open_cold(benchmark, catalog_workspace: Path) -> None:
    """Cold-open a populated SimulationCatalog and close it."""

    def _open() -> None:
        cat = SimulationCatalog(catalog_workspace)
        cat.close()

    benchmark(_open)


@pytest.mark.benchmark(group="catalog")
def test_catalog_list_simulations(benchmark, catalog_workspace: Path) -> None:
    """List every row of a populated catalog on an open connection."""
    with simulation_catalog(catalog_workspace) as cat:

        def _list() -> int:
            return len(cat.list_simulations())

        benchmark(_list)
