"""Solver-bridge extractors used by metric extractors.

Resolves the active flow ``SolverAdapter`` from a trial context and pulls
calibration series (point, boundary, cell). Also owns the station-to-cell
mapping helpers that locate observation stations on a structured grid.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.calibration.metrics.downslope_network import (
    DISTANCE_METHOD,
    seepage_distance_cost,
)
from hydromodpy.calibration.metrics.series import ObservedSeries
from hydromodpy.calibration.observations.network_geometry import geometry_from_run
from hydromodpy.calibration.observations.simulated_network import build_simulated_network
from hydromodpy.core.contracts.observables import (
    ObservableRequest,
    ObservableResult,
    TimeSelector,
)
from hydromodpy.core.exceptions import ObjectiveError
from hydromodpy.core.logging import get_logger
from hydromodpy.simulation.planning.plan import RunContext
from hydromodpy.solver.base.registry import get_solver_adapter

logger = get_logger(__name__)

if TYPE_CHECKING:
    from hydromodpy.calibration.config import (
        CalibOutputDecl,
        CalibOutputNetwork,
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
    try:
        adapter = get_solver_adapter(flow_run.process_type, flow_run.solver)
    except KeyError:
        return None
    run_ctx = RunContext(plan=plan, run=flow_run, state=trial_ctx)
    return adapter, run_ctx


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


def observable_series(result: ObservableResult, *, name: str) -> pd.Series:
    """Rebuild a pandas series from an observable, for the scoring helpers.

    ``score`` aligns on a time index, so an observable that carries one keeps
    it; one that does not falls back to a positional index, exactly as the
    binary readers did before.
    """
    values = np.asarray(result.values, dtype=float).reshape(-1)
    if result.times is not None and len(result.times) == values.size:
        return pd.Series(values, index=result.times, name=name)
    return pd.Series(values, name=name)


def _request_times(time: Any) -> TimeSelector:
    """Map an output declaration's time selector onto the observable contract.

    A declaration may also carry a list of dates, which the reducer handles
    downstream; the adapter is then asked for the whole run.
    """
    return time if time in ("all", "first", "last") else "all"


def observable_request_for_output(
    name: str,
    output: CalibOutputDecl,
    ctx: Any,
) -> ObservableRequest:
    """Translate one calibration output declaration into an observable request.

    This is the single place where the calibration vocabulary meets the solver
    one. An unknown support raises here instead of silently falling through to
    a cell request, which is what used to happen.
    """
    times = _request_times(output.time)
    support = output.support
    if support == "point":
        xy = point_xy_from_output(output)
        if xy is None:
            raise ValueError(f"Point calibration output {name!r} requires x/y or geometry")
        cell = find_cell_at_point(ctx, xy[0], xy[1])
        if cell is None:
            raise NotImplementedError(
                f"Could not map point calibration output {name!r} to a solver cell"
            )
        # The declared variable is not read on this path: a point target is a
        # head target, as it already was before the contract changed.
        return ObservableRequest(id=name, name="head", support="cell", cell=cell, times=times)
    if support == "boundary":
        return ObservableRequest(
            id=name,
            name="discharge",
            support="boundary",
            key=str(output.boundary_id),
            times=times,
        )
    if support == "lake":
        return ObservableRequest(
            id=name,
            name=str(output.variable),
            support="lake",
            key=str(output.lake_id),
            times=times,
        )
    if support == "network":
        # The whole per-cell release field, read at the declared timesteps. The
        # backend decides which of its packages count as a resurgence; this
        # layer never names one.
        return ObservableRequest(id=name, name=str(output.variable), support="cells", times=times)
    if support == "cell":
        if output.row is None or output.col is None:
            raise NotImplementedError(
                f"Cell calibration output {name!r} needs row and col: a flat cell_id "
                "selector is not exposed by any solver."
            )
        return ObservableRequest(
            id=name,
            name=str(output.variable),
            support="cell",
            cell=(int(output.layer), int(output.row), int(output.col)),
            times=times,
        )
    raise ValueError(f"Unknown calibration output support {support!r} on output {name!r}")


def score_network_output(
    run_ctx: RunContext,
    name: str,
    output: CalibOutputNetwork,
    result: ObservableResult,
) -> tuple[list[float], dict[str, float]]:
    """Turn one per-cell release field into the pair ``(D_so, D_os)``.

    The pair is what a block scores; every other number the criterion produces
    travels beside it as a diagnostic, which is how a session records thirty
    quantities per trial without promoting a single run.

    The static geometry is rebuilt here at every trial. It is one graph build
    and three ``O(n_cells)`` passes, measured under a second on a seven
    thousand cell mesh, which is nothing beside one solve; hoisting it would
    mean caching mesh identity across forked trial contexts for no measurable
    gain.
    """
    geometry = geometry_from_run(run_ctx, output)
    simulated = build_simulated_network(
        result.values,
        threshold_m3_s=geometry.threshold_m3_s,
        metric=geometry.metric,
    )
    scored = seepage_distance_cost(
        simulated=simulated,
        observed=geometry.observed,
        outlet=geometry.outlet,
        catchment=geometry.catchment,
        metric=geometry.metric,
        distance_to_observed=geometry.distance_to_observed,
        distance_to_observed_raw=geometry.distance_to_observed_raw,
        cell_area_m2=geometry.cell_area_m2,
        length_scale_m=geometry.length_scale_m,
        saturation_cap_m=geometry.saturation_cap_m,
        excluded=geometry.excluded,
        weighting=output.weighting,
        max_unreachable_fraction=float(output.max_unreachable_fraction),
        roptim_max=float(output.roptim_max),
    )
    if scored.status == "failed":
        raise ObjectiveError(
            f"Output {name!r}: {scored.components.get('frac_unreachable_so', float('nan')):.1%} "
            f"of the simulated support and "
            f"{scored.components.get('frac_unreachable_os', float('nan')):.1%} of the mapped one "
            f"never reach their target, over the {output.max_unreachable_fraction:.0%} bound. "
            "Averaging over a truncated support is a fiction, and the cells dropped are "
            "never a random sample. Two causes read the same here: a routing surface "
            "whose depressions are not resolved, and a trial whose simulated network is "
            "too small for the mapped one to descend into, which is what the ends of a "
            "sweep look like."
        )

    roptim = scored.components["roptim"]
    if np.isfinite(roptim) and roptim > float(output.roptim_max):
        message = (
            f"Output {name!r}: roptim = {roptim:.2f} exceeds the validity bound "
            f"{output.roptim_max:.2f}. The agreement between the two networks is coarser "
            "than the mesh, which qualifies the result; it does not say the calibrated "
            "value is wrong."
        )
        if output.on_roptim_violation == "error":
            raise ObjectiveError(message)
        logger.warning(message)

    logger.info("Output %s scored with distance method %s.", name, DISTANCE_METHOD)

    # D_so has no support when the network is empty, and the pair still has to
    # reproduce the signed residual the bracket reads: it is rebuilt from D_os
    # and the residual so the two never disagree.
    d_os = float(scored.components["D_os"])
    pair = [d_os + scored.signed_gap, d_os]
    diagnostics = {
        f"{name}.{key}": float(value)
        for key, value in {**scored.components, **geometry.diagnostics}.items()
    }
    return pair, diagnostics


def extract_outputs(
    ctx: Any, outputs: Mapping[str, CalibOutputDecl]
) -> tuple[dict[str, list[float]], dict[str, float]]:
    """Ask the flow adapter for every declared output, in one batch.

    One adapter resolution and one call per trial, whatever the number of
    outputs, so a backend opens each binary file once. Translation errors are
    reported per output because they name a declaration the user wrote; the
    extraction itself is a single operation and fails as one.

    Returns the scored values per output and, beside them, the diagnostics the
    network criterion produces, which the caller merges into the components of
    the trial.
    """
    resolved = resolve_flow_adapter(ctx)
    if resolved is None:
        raise NotImplementedError("No flow solver adapter available for calibration extraction")
    adapter, run_ctx = resolved

    requests: list[ObservableRequest] = []
    for name, output in outputs.items():
        try:
            requests.append(observable_request_for_output(name, output, ctx))
        except Exception as exc:
            raise RuntimeError(
                f"Output {name!r} extraction failed: {type(exc).__name__}: {exc}"
            ) from exc

    results = adapter.extract_observables(run_ctx, None, requests, time_index=None)

    simulated: dict[str, list[float]] = {}
    diagnostics: dict[str, float] = {}
    for name, output in outputs.items():
        result = results.get(name)
        if result is None or np.asarray(result.values).size == 0:
            raise NotImplementedError(f"Solver returned no calibration series for output {name!r}")
        if output.support == "network":
            simulated[name], scored = score_network_output(run_ctx, name, output, result)
            diagnostics.update(scored)
        else:
            simulated[name] = slice_time(result.values, output.time, output.reducer)
    return simulated, diagnostics


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

    The lookup runs on the mesh the solver actually wrote: the flow model's
    ``solver_mesh`` (MODFLOW 6, structured or Voronoi), then the MODFLOW-NWT
    structured grid. ``setup.mesh_planar`` is not used, because on a Voronoi
    grid it holds the seed triangulation whose cell order is not the DISV one.
    """
    resolved = resolve_flow_adapter(ctx)
    if resolved is None:
        return None
    _adapter, run_ctx = resolved
    cell = _find_cell_in_solver_mesh(run_ctx, x, y)
    if cell is not None:
        return cell
    return _find_cell_in_modflow_grid(run_ctx, x, y)


def _find_cell_in_solver_mesh(
    run_ctx: RunContext, x: float, y: float
) -> tuple[int, int, int] | None:
    """Locate a cell on the flow model's solver mesh by nearest centroid.

    Returns ``(0, row, col)`` on a structured mesh and ``(0, 0, cell_id)`` on an
    unstructured one, which is the flat DISV selector the MODFLOW 6 head
    extractor reads as ``head[layer, 0, cell_id]``.
    """
    model = run_ctx.state.execution.models_by_run_id.get(run_ctx.run.id)
    mesh = getattr(model, "solver_mesh", None)
    if mesh is None:
        return None
    centroids = np.asarray(mesh.cell_centroids(), dtype=float)
    if centroids.ndim != 2 or centroids.shape[0] == 0 or centroids.shape[1] < 2:
        return None
    deltas = centroids[:, :2] - np.array([x, y], dtype=float)
    idx = int(np.argmin(np.einsum("ij,ij->i", deltas, deltas)))
    if not mesh.is_structured:
        return (0, 0, idx)
    ncol = int(mesh.ncol)
    return (0, idx // ncol, idx % ncol)


def _find_cell_in_modflow_grid(
    run_ctx: RunContext, x: float, y: float
) -> tuple[int, int, int] | None:
    """Locate ``(0, row, col)`` on a MODFLOW-NWT structured grid."""
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
    "extract_outputs",
    "score_network_output",
    "find_cell_at_point",
    "observable_request_for_output",
    "observable_series",
    "point_xy_from_output",
    "resolve_flow_adapter",
    "resolve_station_cells",
    "slice_time",
]
