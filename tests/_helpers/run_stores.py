"""Open the store of a freshly claimed run, the way the pipeline does, for a test.

The run directory is claimed under ``runs/`` of a project, its facts are
written and its field store is created with the grid size given. The store is
returned open; the caller closes it or seals it. No index is opened, except by
:func:`seal_demo_run`, which seals a small run and indexes it as
``hmp catalog reindex`` does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from hydromodpy.core.state.layout import PROJECT_MARKER_FILENAME
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.attempt import RunClaim, claim_run_directory, close_sealed_attempt
from hydromodpy.results.storage.run_facts import RunFacts
from hydromodpy.results.storage.run_store import RunStore
from hydromodpy.results.storage.sealing import seal_completed

RUN_NAME = "demo"
X0, Y0, STEP = 385000.0, 6814000.0, 500.0
STAMPS = pd.to_datetime(["2000-02-01", "2000-03-01", "2000-04-01"])


def claim_run(project: Path, name: str, *, site: str | None = None) -> RunClaim:
    """Claim ``runs/<name>`` of *project*, creating the project marker when absent."""
    project.mkdir(parents=True, exist_ok=True)
    marker = project / PROJECT_MARKER_FILENAME
    if not marker.exists():
        marker.write_text("[workspace]\n", encoding="utf-8")
    return claim_run_directory(project, name, case_id=name, project=project.name, site=site)


def facts_of(
    claim: RunClaim,
    *,
    project: str,
    solver: str = "modflow6",
    solution_key: str | None = None,
    n_cells: int | None = None,
    n_layers: int | None = None,
    n_timesteps: int | None = None,
    **extra: object,
) -> RunFacts:
    """Return the facts of a claimed run, as the prepare step would build them."""
    return RunFacts(
        sim_id=claim.sim_id,
        name=claim.name,
        case_id=claim.name,
        project=project,
        attempt=claim.attempt,
        attempt_id=claim.attempt_id,
        created_at=claim.started_at,
        started_at=claim.started_at,
        solver=solver,
        solution_key=solution_key,
        request_id=solution_key,
        n_cells=n_cells,
        n_layers=n_layers,
        n_timesteps=n_timesteps,
        **extra,
    )


def open_run_store(
    project: Path,
    name: str = "run",
    *,
    n_cells: int = 4,
    n_layers: int = 1,
    n_timesteps: int | None = None,
    solver: str = "modflow6",
    solution_key: str | None = None,
    site: str | None = None,
    create_zarr: bool = True,
    **extra: object,
) -> RunStore:
    """Claim ``runs/<name>`` and return its open store with an empty field store."""
    claim = claim_run(project, name, site=site)
    facts = facts_of(
        claim,
        project=project.name,
        solver=solver,
        solution_key=solution_key,
        n_cells=n_cells,
        n_layers=n_layers,
        n_timesteps=n_timesteps,
        **extra,
    )
    store = RunStore.open(claim.run_dir, facts=facts, workspace=project)
    if create_zarr:
        store.create_zarr(n_cells=n_cells, n_layers=n_layers)
    return store


def seal_demo_run(project: Path, name: str = RUN_NAME) -> tuple[Path, str]:
    """Write, seal and index the run *name* under *project*; return its directory and id.

    Three monthly periods (January to March 2000) on four Lambert-93 cells: a
    head field of one layer, the simulated discharge at the catchment, the
    delineated catchment and the budget. The attempt is closed as the pipeline
    closes it (outcome ``completed``, no ``.hmp/``). Called again with another
    name, it adds a run to the same project.
    """
    store = open_run_store(
        project,
        name,
        n_cells=4,
        n_layers=1,
        n_timesteps=3,
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
        period_start=datetime(2000, 1, 1, tzinfo=UTC),
        period_end=datetime(2000, 4, 1, tzinfo=UTC),
        time_unit="month",
    )
    sim_id = store.sim_id
    verts = np.array(
        [[X0 + i * STEP, Y0 + j * STEP] for j in range(3) for i in range(3)], dtype="float64"
    )
    conn = np.array([[0, 1, 4, 3], [1, 2, 5, 4], [3, 4, 7, 6], [4, 5, 8, 7]], dtype="int32")
    store.write_mesh(sim_id, verts, conn, np.array([50.0, 0.0]))
    store.write_time(sim_id, STAMPS.values.astype("datetime64[s]").astype("int64"))
    store.write_crs(sim_id, crs_wkt="EPSG:2154", epsg_code=2154)
    for step in range(3):
        store.write_field(
            sim_id,
            "head",
            step,
            np.array([[12.5, 14.25, 16.75, 19.0]]) + step,
            n_timesteps=3 if step == 0 else None,
        )
    store.write_timeseries(
        sim_id, "catchment", "discharge", pd.Series([1.0, 2.0, 3.0], index=STAMPS), unit="m3/s"
    )
    store.write_geographic_feature(
        sim_id,
        "watershed",
        gpd.GeoDataFrame(geometry=[box(X0, Y0, X0 + 2 * STEP, Y0 + 2 * STEP)], crs="EPSG:2154"),
    )
    store.write_budgets(
        sim_id,
        [
            {"timestep": t, "zone_id": "catchment", "component": "recharge", "flux_in": 1.0 + t}
            for t in range(3)
        ],
    )
    run_dir = store.run_dir
    seal_completed(store)
    close_sealed_attempt(run_dir)
    rebuild_index(project)
    return run_dir, sim_id


__all__ = ["RUN_NAME", "claim_run", "facts_of", "open_run_store", "seal_demo_run"]
