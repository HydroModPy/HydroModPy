"""Golden regression test for the writes of a run store, read back from the index.

Pins the data surface of the most-used write methods of
:class:`~hydromodpy.results.storage.run_store.RunStore` against a fixed
baseline: a run is claimed, written, sealed and indexed, and the rows the
index holds are compared. Non-deterministic clock fields (``valid_from``,
``created_at``, ``ended_at``, ``written_at`` parquet kv) and the run id, drawn
at claim time, are excluded.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from hydromodpy import __version__ as HYDROMODPY_VERSION
from hydromodpy.results.catalog.facade import Catalog
from hydromodpy.results.record.manifest import MetricRow
from hydromodpy.results.storage.sealing import seal_completed
from tests._helpers.fixtures_catalog import simulation_catalog
from tests._helpers.run_stores import open_run_store

# Fields whose value depends on wall-clock time. Strip before snapshotting.
_NON_DETERMINISTIC_FIELDS: frozenset[str] = frozenset(
    {
        "valid_from",
        "created_at",
        "ended_at",
        "started_at",
        "fetched_at",
    }
)


def _row_tuple_text(rows: list[tuple]) -> str:
    """Render a list of row tuples as a deterministic JSON string."""
    serialised = [[_render_value(v) for v in row] for row in rows]
    serialised.sort()
    return json.dumps(serialised, sort_keys=True, default=str)


def _render_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool | int | float | str):
        return value
    return str(value)


def _table_data_sha256(parquet_path: Path) -> str:
    """Hash the row data of a parquet file (schema-aware, metadata-free), run id left out."""
    table = pq.read_table(parquet_path)
    payload = [{k: v for k, v in row.items() if k != "sim_id"} for row in table.to_pylist()]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _capture_state(catalog: Catalog, sim_id: str) -> dict[str, Any]:
    """Capture deterministic state after the standard write sequence, run id masked."""
    parameters = catalog.connection.execute(
        "SELECT sim_id, param_name, zone_id, value, unit, parameterization "
        "FROM parameters WHERE sim_id = ? ORDER BY param_name",
        [sim_id],
    ).fetchall()
    metrics = catalog.connection.execute(
        "SELECT sim_id, station_id, variable, metric, value "
        "FROM metrics WHERE sim_id = ? ORDER BY metric",
        [sim_id],
    ).fetchall()
    run_env = catalog.connection.execute(
        "SELECT sim_id, hydromodpy_version, solver_name, rng_seed "
        "FROM runs_environment WHERE sim_id = ?",
        [sim_id],
    ).fetchall()
    objective = catalog.connection.execute(
        "SELECT sim_id, scientific_objective FROM simulations WHERE sim_id = ?",
        [sim_id],
    ).fetchall()
    state = {
        "parameters": _row_tuple_text(parameters),
        "metrics": _row_tuple_text(metrics),
        "run_env": _row_tuple_text(run_env),
        "objective": _row_tuple_text(objective),
    }
    return {key: text.replace(sim_id, SIM_ID_MASK) for key, text in state.items()}


def _run_standard_writes(project: Path) -> str:
    """Apply a fixed set of write calls, seal the run and return its sim_id."""
    store = open_run_store(
        project,
        "golden-sim",
        n_cells=4,
        n_layers=1,
        scientific_objective="calibration of K field",
    )
    sid = store.sim_id
    store.write_parameters(
        sid,
        [
            {"param_name": "K", "value": 1.5, "unit": "m/d"},
            {"param_name": "S", "value": 1e-4, "unit": "1/m"},
        ],
    )
    store.write_metric(sid, MetricRow(station="P01", variable="head", metric="nse", value=0.91))
    store.write_run_environment(sid, solver_name="modflow6", rng_seed=42)
    idx = pd.date_range("2020-01-01", periods=3, freq="D", tz="UTC")
    store.write_timeseries(
        sid,
        "P01",
        "head",
        pd.Series(np.array([10.0, 11.0, 12.0]), index=idx),
    )
    seal_completed(store)
    return sid


SIM_ID_MASK = "<sim_id>"
"""Stands for the run id in the captured rows: the id is drawn when the run is claimed."""

# Golden constants. The rows are the ones the catalog writer produced at
# commit a89658f85, less the columns the run record no longer carries
# (study_area_name, outlet_x, outlet_y). The timeseries hash is the one of
# that writer's file with the sim_id column left out (measured at d99780c52).
# Updating these is allowed only when an intentional data change is shipped
# together.
GOLDEN_PARAMETERS = (
    '[["<sim_id>", "K", "catchment", 1.5, "m d-1", null], '
    '["<sim_id>", "S", "catchment", 0.0001, "m-1", null]]'
)
GOLDEN_METRICS = '[["<sim_id>", "P01", "head", "nse", 0.91]]'
GOLDEN_RUN_ENV = json.dumps(
    [[SIM_ID_MASK, HYDROMODPY_VERSION, "modflow6", 42]],
    sort_keys=True,
)
GOLDEN_OBJECTIVE = '[["<sim_id>", "calibration of K field"]]'
GOLDEN_TIMESERIES_SHA256 = "f85f88784e3b0a113aa7cb5fcb4e0255f046530e76de47f5ab889a1f59830e1b"


def test_writes_golden(tmp_path: Path) -> None:
    """Pin the deterministic surface of the write API to a known baseline."""
    project = tmp_path / "ws"
    sid = _run_standard_writes(project)
    with simulation_catalog(project) as catalog:
        state = _capture_state(catalog, sid)
        ts_sha = _table_data_sha256(catalog.tables_dir_for(sid) / "timeseries.parquet")

    assert state["parameters"] == GOLDEN_PARAMETERS
    assert state["metrics"] == GOLDEN_METRICS
    assert state["run_env"] == GOLDEN_RUN_ENV
    assert state["objective"] == GOLDEN_OBJECTIVE
    assert ts_sha == GOLDEN_TIMESERIES_SHA256
