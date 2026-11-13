"""One small stored run for the figure tests, written the way the pipeline writes one.

Twelve Lambert-93 cells on a 3 by 4 grid, 500 m wide and 500 m high except the last
column, which is 1,000 m wide, so the cell areas are unequal. There are two layers, four monthly periods
from January 2001. It holds a head, a recharge and a drain budget term as cell flows,
a topography, a simulated discharge at the catchment and at one gauge, a rainfall series at that gauge, the observed
discharge of that gauge, its scores and the descent basin of the catchment.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

import hydromodpy as hmp
from hydromodpy.core.scope import OBSERVED
from hydromodpy.core.toml_io.writer import dumps as dump_toml
from hydromodpy.results.catalog.indexer import rebuild_index
from hydromodpy.results.run.view import Run
from hydromodpy.results.storage.attempt import close_sealed_attempt
from hydromodpy.results.storage.contract import RUN_CONFIG_FILENAME
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.run_builders import GAUGE, score
from tests._helpers.run_stores import open_run_store

NROW, NCOL, STEP = 3, 4, 500.0
COLUMN_X = np.array([0.0, 500.0, 1000.0, 1500.0, 2500.0])
"""Cell edges in x from the grid origin, m. The last column is twice as wide."""
AREAS = np.tile(np.diff(COLUMN_X) * STEP, NROW)
"""Area of each cell in m2, in cell order."""
X0, Y0 = 385000.0, 6814000.0
N_CELLS, N_LAYERS, N_PERIODS = NROW * NCOL, 2, 4
ZONE_AREA = float(AREAS[: N_CELLS - NCOL].sum())
"""Area of the catchment zone, the first two rows, in m2."""
STARTS = pd.date_range("2001-01-01", periods=N_PERIODS, freq="MS")
STAMPS = pd.date_range("2001-02-01", periods=N_PERIODS, freq="MS")
HEAD_TOP = np.linspace(100.0, 111.0, N_CELLS)
RECHARGE_M3S = 2.0e-3
"""Recharge of each cell at period 0, m3/s. It grows by one tenth each period."""


def write_run(project: Path, name: str = "stored", head_shift: float = 0.0) -> str:
    """Write, seal and index one run under ``project`` and return its run id.

    ``head_shift`` raises every head by that many metres, to give a second run on one mesh.
    """
    store = open_run_store(
        project,
        name,
        n_cells=N_CELLS,
        n_layers=N_LAYERS,
        n_timesteps=N_PERIODS,
        crs_epsg=2154,
        crs_wkt="EPSG:2154",
        period_start=datetime(2001, 1, 1, tzinfo=UTC),
        period_end=datetime(2001, 5, 1, tzinfo=UTC),
        time_unit="month",
    )
    sid = store.sim_id
    verts = np.array(
        [[X0 + COLUMN_X[i], Y0 + j * STEP] for j in range(NROW + 1) for i in range(NCOL + 1)], float
    )
    faces = np.array(
        [
            [j * (NCOL + 1) + i, j * (NCOL + 1) + i + 1, (j + 1) * (NCOL + 1) + i + 1,
             (j + 1) * (NCOL + 1) + i]
            for j in range(NROW)
            for i in range(NCOL)
        ],
        dtype="int32",
    )  # fmt: skip
    store.write_mesh(sid, verts, faces, np.array([120.0, 60.0, 0.0]))
    store.write_time(sid, STAMPS.values.astype("datetime64[s]").astype("int64"))
    store.write_crs(sid, crs_wkt="EPSG:2154", epsg_code=2154)
    for step in range(N_PERIODS):
        head = np.stack([HEAD_TOP - 1.0 + step, HEAD_TOP - 6.0 + step]) + head_shift
        recharge = np.zeros((N_LAYERS, N_CELLS))
        recharge[0] = RECHARGE_M3S * (1.0 + 0.1 * step)
        count = N_PERIODS if step == 0 else None
        store.write_field(sid, "head", step, head, n_timesteps=count)
        for term, values in (("recharge", recharge), ("drain", -0.5 * recharge)):
            store.write_field(sid, term, step, values, n_timesteps=count, subgroup="budget")
    simulated = pd.Series([1.0, 2.0, 3.0, 2.5], index=STAMPS)
    store.write_timeseries(sid, "catchment", "discharge", simulated, unit="m3/s")
    store.write_timeseries(sid, GAUGE, "discharge", simulated, unit="m3/s")
    store.write_timeseries(sid, GAUGE, "rainfall", 3.0 - simulated, unit="m3/s")
    store.write_timeseries(sid, GAUGE, "discharge", 1.1 * simulated, unit="m3/s", source=OBSERVED)
    score(store, 0.8)
    store.write_budgets(
        sid,
        [
            {"timestep": t, "zone_id": "catchment", "component": "recharge", "flux_in": 1.0 + t}
            for t in range(N_PERIODS)
        ],
    )
    reaches = [
        {
            "reach_id": f"n:{i}", "network_id": "n", "reach": i, "cell2d": i - 1, "layer": 0,
            "rtp": 100.0, "rbth": 1.0, "rlen": STEP, "rwid": 2.0, "rgrd": 0.01 * i, "rhk": 1e-5,
            "manning": 0.035, "strahler": 1, "ustrf": 1.0, "downstream": [i + 1] * (i < 3),
        }
        for i in (1, 2, 3)
    ]  # fmt: skip
    store.write_view(sid, "sfr_reaches", reaches)
    zeros = np.zeros(N_CELLS)
    basin = np.ones(N_CELLS, dtype=bool)
    basin[-NCOL:] = False
    sz = store.open_zarr(sid)
    try:
        sz.write_static_field("topography", HEAD_TOP + 8.0, subgroup="mesh")
        sz.write_descent(
            receiver=np.full(N_CELLS, -1), surface=HEAD_TOP, base_level=zeros > 0,
            constant_head=zeros > 0, raised=zeros > 0, channel=zeros > 0, pinned=zeros > 0,
            attrs={}, basin=basin,
            basin_attrs={"descent_outlet": 0, "basin_rule": "outlet"},
        )  # fmt: skip
    finally:
        sz.close()
    run_dir = store.run_dir
    (run_dir / RUN_CONFIG_FILENAME).write_text(dump_toml({"display": {"theme": "print"}}))
    seal_completed(store)
    close_sealed_attempt(run_dir)
    rebuild_index(project)
    return sid


def open_stored_run(project: Path) -> Run:
    """Return the run written by :func:`write_run`, opened through the public API."""
    write_run(project)
    return hmp.open(project).store["stored"]
