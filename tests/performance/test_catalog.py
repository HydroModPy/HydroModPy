"""Catalog open/list baseline benchmarks (DuckDB index reader).

Guards the thin HydroModPy reader of a project index: the read-only DuckDB
connection with its payload views, and a ``list_simulations`` query over an
index of many sealed runs. A regression in ``Catalog`` open or query shows up
here as a pairwise-ratio drift in ``perf.yml``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.catalog.indexer import rebuild_index
from tests._helpers.fixtures_catalog import simulation_catalog
from tests._helpers.sealed_runs import make_project, seal_run

pytestmark = pytest.mark.performance

N_SIMS = 100


@pytest.fixture(scope="function")
def catalog_workspace(tmp_path: Path) -> Path:
    """Build a project of ``N_SIMS`` sealed runs and its index."""
    project = make_project(tmp_path / "workspace")
    for i in range(N_SIMS):
        seal_run(project, f"sim_{i}", project="perf", sim_id=f"00000000-0000-0000-0000-{i:012d}")
    rebuild_index(project)
    return project


@pytest.mark.benchmark(group="catalog")
def test_catalog_open_cold(benchmark, catalog_workspace: Path) -> None:
    """Cold-open a populated Catalog and close it."""

    def _open() -> None:
        cat = Catalog(catalog_workspace)
        cat.close()

    benchmark(_open)


@pytest.mark.benchmark(group="catalog")
def test_catalog_list_simulations(benchmark, catalog_workspace: Path) -> None:
    """List every row of a populated catalog on an open connection."""
    with simulation_catalog(catalog_workspace) as cat:

        def _list() -> int:
            return len(cat.list_simulations())

        benchmark(_list)
