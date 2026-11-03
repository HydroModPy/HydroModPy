"""A run with a field, a series, a layer and a budget, sealed by its store and indexed.

Three monthly periods (January to March 2000) on four Lambert-93 cells: a head
field of one layer, the simulated discharge at the catchment, the delineated
catchment and the budget. The run is claimed and written the way the pipeline
does (``tests/_helpers/run_stores.py``), sealed by
:func:`hydromodpy.results.storage.sealing.seal_completed`, its attempt closed
as the pipeline closes it (outcome ``completed``, no ``.hmp/``), and the index
is rebuilt from disk, as ``hmp catalog reindex`` does.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_stores import open_run_store

RUN_NAME = "demo"
X0, Y0, STEP = 385000.0, 6814000.0, 500.0
STAMPS = pd.to_datetime(["2000-02-01", "2000-03-01", "2000-04-01"])


def seal_demo_run(project: Path, name: str = RUN_NAME) -> tuple[Path, str]:
    """Write, seal and index the run *name* under *project*; return its directory and id.

    Called again with another name, it adds a run to the same project.
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
