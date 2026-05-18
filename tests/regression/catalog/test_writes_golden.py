"""Golden regression test for WritesMixin.

Pins the data surface of the most-used write methods against a fixed
baseline. The goal is to make the mixin-split refactor (DuckDB / Parquet /
Zarr) byte-equivalent on stable columns. Non-deterministic clock fields
(``valid_from``, ``created_at``, ``ended_at``, ``written_at`` parquet kv)
are excluded.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

from hydromodpy.results.catalog import SimulationCatalog

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
    """Hash the row data of a parquet file (schema-aware, metadata-free)."""
    table = pq.read_table(parquet_path)
    payload = table.to_pylist()
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _capture_state(catalog: SimulationCatalog, sim_id: str) -> dict[str, Any]:
    """Capture deterministic state after the standard write sequence."""
    parameters = catalog.connection.execute(
        "SELECT sim_id, param_name, zone_id, value, unit, parameterization "
        "FROM parameters WHERE sim_id = ? ORDER BY param_name",
        [sim_id],
    ).fetchall()
    metrics = catalog.connection.execute(
        "SELECT sim_id, station_id, variable, metric_name, value, n_samples "
        "FROM metrics WHERE sim_id = ? ORDER BY metric_name",
        [sim_id],
    ).fetchall()
    run_env = catalog.connection.execute(
        "SELECT sim_id, hydromodpy_version, solver_name, rng_seed "
        "FROM runs_environment WHERE sim_id = ?",
        [sim_id],
    ).fetchall()
    objective = catalog.connection.execute(
        "SELECT sim_id, scientific_objective, study_area_name, outlet_x, outlet_y "
        "FROM simulations WHERE sim_id = ?",
        [sim_id],
    ).fetchall()
    return {
        "parameters": _row_tuple_text(parameters),
        "metrics": _row_tuple_text(metrics),
        "run_env": _row_tuple_text(run_env),
        "objective": _row_tuple_text(objective),
    }


def _run_standard_writes(catalog: SimulationCatalog) -> str:
    """Apply a fixed set of write calls and return the new sim_id."""
    sid = str(uuid.UUID("12345678-1234-5678-1234-567812345678"))
    reg = catalog.register_simulation(
        sid,
        name="golden-sim",
        project="golden",
        solver="modflow6",
        n_cells=4,
        n_layers=1,
    )
    if reg.zarr is not None:
        reg.zarr.close()
    catalog.write_parameters(
        sid,
        [
            {"param_name": "K", "value": 1.5, "unit": "m/d"},
            {"param_name": "S", "value": 1e-4, "unit": "1/m"},
        ],
    )
    catalog.write_metric(sid, "P01", "nse", 0.91)
    catalog.write_run_environment(sid, solver_name="modflow6", rng_seed=42)
    catalog.write_scientific_objective(
        sid,
        "calibration of K field",
        study_area_name="Test catchment",
        outlet_x=1.0,
        outlet_y=2.0,
    )
    idx = pd.date_range("2020-01-01", periods=3, freq="D", tz="UTC")
    catalog.write_timeseries(
        sid,
        "P01",
        "head",
        pd.Series(np.array([10.0, 11.0, 12.0]), index=idx),
    )
    return sid


# Golden constants captured against the writes.py implementation at
# commit a89658f85 (parent of the mixin split). Updating these is allowed
# only when an intentional data change is shipped together.
GOLDEN_PARAMETERS = (
    '[["12345678-1234-5678-1234-567812345678", "K", "__global__", '
    '1.5, "m/d", null], '
    '["12345678-1234-5678-1234-567812345678", "S", "__global__", '
    '0.0001, "1/m", null]]'
)
GOLDEN_METRICS = '[["12345678-1234-5678-1234-567812345678", "P01", "head", "nse", 0.91, null]]'
GOLDEN_RUN_ENV = '[["12345678-1234-5678-1234-567812345678", "1.0.0", "modflow6", 42]]'
GOLDEN_OBJECTIVE = (
    '[["12345678-1234-5678-1234-567812345678", '
    '"calibration of K field", "Test catchment", 1.0, 2.0]]'
)
GOLDEN_TIMESERIES_SHA256 = "9b63e82da82f5bdabaf8fc1becaaee8f3496555bda6e0d35e48e6d52826dd559"


def test_writes_golden(tmp_path: Path) -> None:
    """Pin the deterministic surface of the write API to a known baseline."""
    catalog = SimulationCatalog(tmp_path / "ws")
    try:
        sid = _run_standard_writes(catalog)
        state = _capture_state(catalog, sid)
        ts_path = catalog._paths.parquet_path_for(sid, "timeseries")
        ts_sha = _table_data_sha256(ts_path)
    finally:
        catalog.close()

    assert state["parameters"] == GOLDEN_PARAMETERS
    assert state["metrics"] == GOLDEN_METRICS
    assert state["run_env"] == GOLDEN_RUN_ENV
    assert state["objective"] == GOLDEN_OBJECTIVE
    assert ts_sha == GOLDEN_TIMESERIES_SHA256
