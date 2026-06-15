"""Solver-bridge extractors used by metric extractors.

Resolves the active flow ``SolverAdapter`` from a trial context and pulls
calibration series (point, boundary, cell). Also owns the station-to-cell
mapping helpers that locate observation stations on a structured grid.
"""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.simulation.planning.plan import RunContext
from hydromodpy.solver.base.registry import get_solver_adapter

if TYPE_CHECKING:
    from hydromodpy.calibration.config import (
        CalibOutputBoundary,
        CalibOutputCell,
        CalibOutputLake,
        CalibOutputPoint,
    )


def resolve_flow_adapter(trial_ctx: Any) -> tuple[Any, RunContext] | None:
    """Return ``(adapter, run_ctx)`` for the active flow run, or ``None``.

    A calibration trial runs exactly one flow process by design. This helper
    returns the first such ``ProcessRun`` it finds along with a freshly
    instantiated ``SolverAdapter`` and a ``RunContext`` whose ``state`` is the
    trial context itself.
    """
    registry_state = getattr(trial_ctx, "execution", None)
    if registry_state is None:
        return None
    models = registry_state.models_by_run_id or {}
    if not models:
        return None
    plan = getattr(registry_state, "simulation_plan", None)
    if plan is None:
        return None

    flow_run = None
    for run in plan.runs:
        if run.process_type == "flow" and run.id in models:
            flow_run = run
            break
    if flow_run is None:
        return None
    if flow_run.solver == "boussinesq":
        raise NotImplementedError(
            "Calibration extraction is not implemented for solver 'boussinesq'"
        )

    try:
        adapter = get_solver_adapter(flow_run.process_type, flow_run.solver)
    except KeyError:
        return None
    run_ctx = RunContext(plan=plan, run=flow_run, state=trial_ctx)
    return adapter, run_ctx


def _adapter_supports_keyword(adapter: Any, keyword: str) -> bool:
    """Return True when ``extract_calibration_series`` accepts ``keyword``."""
    signature = inspect.signature(adapter.extract_calibration_series)
    return keyword in signature.parameters or any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )


def call_extract_calibration_series(
    adapter: Any,
    run_ctx: RunContext,
    *,
    variable: str,
    station_cells: Mapping[str, Any] | None = None,
    boundary_id: str | None = None,
    lake_id: str | None = None,
    time_index: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """Call an adapter while enforcing explicit boundary/lake filtering support."""
    kwargs: dict[str, Any] = {
        "variable": variable,
        "time_index": time_index,
    }
    if station_cells is not None:
        kwargs["station_cells"] = station_cells
    if boundary_id is not None:
        if not _adapter_supports_keyword(adapter, "boundary_id"):
            raise NotImplementedError(
                f"Solver {run_ctx.run.solver!r} cannot filter calibration boundary_id="
                f"{boundary_id!r}"
            )
        kwargs["boundary_id"] = boundary_id
    if lake_id is not None:
        if not _adapter_supports_keyword(adapter, "lake_id"):
            raise NotImplementedError(
                f"Solver {run_ctx.run.solver!r} cannot extract calibration lake_id={lake_id!r}"
            )
        kwargs["lake_id"] = lake_id
    return adapter.extract_calibration_series(run_ctx, None, **kwargs)


def slice_time(values: np.ndarray, time: Any, reducer: str) -> list[float]:
    """Apply ``time`` selector and ``reducer`` to a 1D array of simulated values."""
    arr = np.asarray(values, dtype=float).ravel()
    if arr.size == 0:
        return []
    if time == "first":
        arr = arr[:1]
    elif time == "last":
        arr = arr[-1:]
    if reducer == "mean":
        return [float(np.nanmean(arr))]
    if reducer == "sum":
        return [float(np.nansum(arr))]
    if reducer == "last":
        return [float(arr[-1])]
    return [float(v) for v in arr]


def _coerce_length_to_m(value: Any) -> float | None:
    """Pull the magnitude in metres from a pint Quantity or bare number."""
    if value is None:
        return None
    to_m = getattr(value, "to", None)
    if callable(to_m):
        try:
            return float(value.to("m").magnitude)
        except Exception:
            pass
    return float(value)


def point_xy_from_output(output: CalibOutputPoint) -> tuple[float, float] | None:
    """Return planar point coordinates from an output declaration."""
    x_m = _coerce_length_to_m(output.x)
    y_m = _coerce_length_to_m(output.y)
    if x_m is not None and y_m is not None:
        return x_m, y_m
    geometry = output.geometry
    if not geometry:
        return None
    if str(geometry.get("type", "")).lower() != "point":
        raise ValueError("Point calibration geometry must be a GeoJSON Point")
    coords = geometry.get("coordinates")
    if not isinstance(coords, (list, tuple)) or len(coords) < 2:
        raise ValueError("Point calibration geometry requires two coordinates")
    return float(coords[0]), float(coords[1])


def extract_point(ctx: Any, output: CalibOutputPoint) -> list[float]:
    """Extract a head time series at the (x, y) point declared on ``output``."""
    resolved = resolve_flow_adapter(ctx)
    if resolved is None:
        raise NotImplementedError("No flow solver adapter available for point extraction")
    adapter, run_ctx = resolved

    xy = point_xy_from_output(output)
    if xy is None:
        raise ValueError("Point calibration output requires x/y or geometry")

    cell = find_cell_at_point(ctx, xy[0], xy[1])
    if cell is None:
        raise NotImplementedError("Could not map point calibration output to a solver cell")
    sim = call_extract_calibration_series(
        adapter,
        run_ctx,
        variable="head",
        station_cells={"_pt": cell},
        time_index=None,
    )
    if sim.empty:
        raise NotImplementedError("Solver returned no point calibration series")
    return slice_time(sim.values, output.time, output.reducer)


def extract_boundary(ctx: Any, output: CalibOutputBoundary) -> list[float]:
    """Extract a boundary time series filtered by ``boundary_id``."""
    resolved = resolve_flow_adapter(ctx)
    if resolved is None:
        raise NotImplementedError("No flow solver adapter available for boundary extraction")
    adapter, run_ctx = resolved

    sim = call_extract_calibration_series(
        adapter,
        run_ctx,
        variable="discharge",
        boundary_id=str(output.boundary_id),
        time_index=None,
    )
    if sim.empty:
        raise NotImplementedError("Solver returned no boundary calibration series")
    return slice_time(sim.values, output.time, output.reducer)


def extract_lake(ctx: Any, output: CalibOutputLake) -> list[float]:
    """Extract a lake stage time series for the lake named by ``output.lake_id``."""
    resolved = resolve_flow_adapter(ctx)
    if resolved is None:
        raise NotImplementedError("No flow solver adapter available for lake extraction")
    adapter, run_ctx = resolved

    sim = call_extract_calibration_series(
        adapter,
        run_ctx,
        variable="lake_stage",
        lake_id=str(output.lake_id),
        time_index=None,
    )
    if sim.empty:
        raise NotImplementedError("Solver returned no lake calibration series")
    return slice_time(sim.values, output.time, output.reducer)


def extract_cell(ctx: Any, output: CalibOutputCell) -> list[float]:
    """Extract a head time series at an explicit cell selector."""
    resolved = resolve_flow_adapter(ctx)
    if resolved is None:
        raise NotImplementedError("No flow solver adapter available for cell extraction")
    adapter, run_ctx = resolved
    if output.row is not None and output.col is not None:
        selector: Any = (int(output.layer), int(output.row), int(output.col))
    elif output.cell_id is not None:
        raise NotImplementedError(
            f"Solver {run_ctx.run.solver!r} does not expose flat cell_id calibration selectors"
        )
    else:
        raise ValueError("Cell calibration output requires row/col or cell_id")
    sim = call_extract_calibration_series(
        adapter,
        run_ctx,
        variable=output.variable,
        station_cells={"_cell": selector},
        time_index=None,
    )
    if sim.empty:
        raise NotImplementedError("Solver returned no cell calibration series")
    return slice_time(sim.values, output.time, output.reducer)


# ---------------------------------------------------------------------------
# Station-to-cell mapping
# ---------------------------------------------------------------------------


def resolve_station_cells(
    ctx: Any,
    observed: list[ObservedSeries],
) -> dict[str, tuple[int, int, int]]:
    """Resolve station ids to structured ``(layer, row, col)`` cells."""
    piezo = getattr(ctx.loaded_data, "piezometry", None)
    if piezo is None:
        return {}
    points = getattr(piezo, "points", None) or []
    cells: dict[str, tuple[int, int, int]] = {}
    for obs_rec in observed:
        for rec in points:
            if str(rec.station_id) == obs_rec.station_id:
                cell_ij = getattr(rec, "cell_ij", None)
                cell = (
                    _coerce_cell_ij(cell_ij)
                    if cell_ij is not None
                    else _coerce_structured_cell(
                        getattr(rec, "cell", None) or getattr(rec, "station_cell", None)
                    )
                )
                if cell is None:
                    xy = _xy_from_record(rec)
                    if xy is not None:
                        cell = find_cell_at_point(ctx, xy[0], xy[1])
                if cell is not None:
                    cells[obs_rec.station_id] = cell
                break
    return cells


def _coerce_cell_ij(value: Any) -> tuple[int, int, int] | None:
    """Return ``(layer, row, col)`` from ``(row, col[, layer])`` metadata."""
    try:
        parts = tuple(value)
    except TypeError:
        return None
    if len(parts) == 2:
        return (0, int(parts[0]), int(parts[1]))
    if len(parts) >= 3:
        return (int(parts[2]), int(parts[0]), int(parts[1]))
    return None


def _coerce_structured_cell(value: Any) -> tuple[int, int, int] | None:
    """Return ``(layer, row, col)`` from common station metadata shapes."""
    if value is None:
        return None
    if isinstance(value, Mapping):
        layer = value.get("layer", value.get("k", 0))
        row = value.get("row", value.get("i"))
        col = value.get("col", value.get("j"))
        if row is None or col is None:
            return None
        return (int(layer), int(row), int(col))
    try:
        parts = tuple(value)
    except TypeError:
        return None
    if len(parts) == 2:
        return (0, int(parts[0]), int(parts[1]))
    if len(parts) >= 3:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    return None


def _xy_from_record(record: Any) -> tuple[float, float] | None:
    """Extract planar x/y coordinates from an observation record."""
    for x_name, y_name in (("x", "y"), ("easting", "northing"), ("longitude", "latitude")):
        x_val = getattr(record, x_name, None)
        y_val = getattr(record, y_name, None)
        if x_val is not None and y_val is not None:
            return float(x_val), float(y_val)
    geometry = getattr(record, "geometry", None)
    x_val = getattr(geometry, "x", None)
    y_val = getattr(geometry, "y", None)
    if x_val is not None and y_val is not None:
        return float(x_val), float(y_val)
    return None


def find_cell_at_point(ctx: Any, x: float, y: float) -> tuple[int, int, int] | None:
    """Return the closest ``(layer, row, col)`` to ``(x, y)`` on layer 0.

    Tries cell centroids from ``setup.mesh_planar`` first, then falls back to
    a MODFLOW-NWT structured grid lookup.
    """
    mesh = getattr(getattr(ctx, "setup", None), "mesh_planar", None)
    if mesh is not None:
        centroids = getattr(mesh, "cell_centroids", None) or getattr(mesh, "centroids", None)
        if centroids is not None:
            try:
                arr = np.asarray(centroids, dtype=float)
            except Exception:
                arr = None
            if arr is not None and arr.ndim == 2 and arr.shape[1] >= 2:
                deltas = arr[:, :2] - np.array([x, y], dtype=float)
                distances = np.einsum("ij,ij->i", deltas, deltas)
                idx = int(np.argmin(distances))
                nrow = int(getattr(mesh, "nrow", 0) or 0)
                ncol = int(getattr(mesh, "ncol", 0) or 0)
                if nrow > 0 and ncol > 0 and idx < nrow * ncol:
                    return (0, idx // ncol, idx % ncol)

    return _find_cell_in_modflow_grid(ctx, x, y)


def _find_cell_in_modflow_grid(ctx: Any, x: float, y: float) -> tuple[int, int, int] | None:
    """Locate ``(0, row, col)`` on a MODFLOW-NWT structured grid."""
    resolved = resolve_flow_adapter(ctx)
    if resolved is None:
        return None
    _adapter, run_ctx = resolved
    model = run_ctx.state.execution.models_by_run_id.get(run_ctx.run.id)
    if model is None:
        return None
    modelgrid = getattr(getattr(model, "mf", None), "modelgrid", None)
    if modelgrid is None:
        return None
    xc = getattr(modelgrid, "xcellcenters", None)
    yc = getattr(modelgrid, "ycellcenters", None)
    if xc is None or yc is None:
        return None
    try:
        xc_arr = np.asarray(xc, dtype=float)
        yc_arr = np.asarray(yc, dtype=float)
    except Exception:
        return None
    if xc_arr.shape != yc_arr.shape or xc_arr.ndim != 2:
        return None
    distances = (xc_arr - x) ** 2 + (yc_arr - y) ** 2
    flat_idx = int(np.argmin(distances))
    nrow, ncol = xc_arr.shape
    return (0, flat_idx // ncol, flat_idx % ncol)


__all__ = [
    "resolve_flow_adapter",
    "call_extract_calibration_series",
    "slice_time",
    "point_xy_from_output",
    "extract_point",
    "extract_boundary",
    "extract_cell",
    "extract_lake",
    "resolve_station_cells",
    "find_cell_at_point",
]
