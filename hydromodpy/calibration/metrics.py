"""RAM metric extraction for lightweight calibration trials.

During a calibration loop, each trial runs in ``lightweight`` mode: the
solver still writes its binary output (``.hds``, ``.cbc``, ...) to the
workspace scratch folder, but no Zarr / Parquet / catalog rows are
created. The optimizer only needs a scalar objective value to drive the
ask/tell loop. This module loads observations once, then for every trial
asks the run's :class:`SolverAdapter` to produce the simulated series via
``extract_calibration_series`` and scores it against the observations.

Solver coverage is owned by the adapters: the lightweight reader for
MODFLOW-NWT and MODFLOW 6 lives in
``hydromodpy.solver.modflow_common.calibration_extractors``. Unsupported
adapters raise explicit errors so failed calibration trials do not look
like valid NaN-scored evaluations.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.calibration.objective import (
    HIGHER_IS_BETTER,
    METRICS,
    build_objective_from_config,
)
from hydromodpy.core.logging import get_logger
from hydromodpy.results.time_alignment import (
    align_observed_simulated,
    observed_on_simulation_index,
)
from hydromodpy.simulation.planning.plan import RunContext
from hydromodpy.solver.base.registry import get_solver_adapter

if TYPE_CHECKING:
    from hydromodpy.calibration.config import CalibObjectiveBlockDecl, CalibOutputDecl

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Observation adapter
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObservedSeries:
    """One observed timeseries indexed by time."""

    station_id: str
    variable: str
    series: pd.Series  # DatetimeIndex, float values


def _load_observed(
    ctx: Any,
    variable: str,
) -> list[ObservedSeries]:
    """Pull observation timeseries from the loaded-data context.

    ``variable`` is the calibration-target variable (``"discharge"``,
    ``"head"``). Discharge comes from ``hydrometry``, head from
    ``piezometry``. The helper returns a list of ``ObservedSeries`` -
    one per station - so multi-station calibration works uniformly.
    """
    field_name = {"discharge": "hydrometry", "head": "piezometry"}.get(variable)
    if field_name is None:
        return []
    result = getattr(ctx.loaded_data, field_name, None)
    if result is None:
        return []
    points = getattr(result, "points", None) or []
    out: list[ObservedSeries] = []
    for rec in points:
        try:
            df = getattr(rec, "data", None)
            if df is None or df.empty:
                continue
            idx = pd.to_datetime(df["datetime"])
            if idx.dt.tz is not None:
                idx = idx.dt.tz_localize(None)
            series = pd.Series(
                df["value"].astype("float64").values,
                index=pd.DatetimeIndex(idx),
                name=f"{rec.variable}_obs",
            )
            out.append(
                ObservedSeries(
                    station_id=str(rec.station_id),
                    variable=str(rec.variable),
                    series=series,
                )
            )
        except Exception:
            logger.debug("Could not convert observation %s to series", rec)
    return out


# ---------------------------------------------------------------------------
# Adapter resolution: pick the active flow run and its SolverAdapter
# ---------------------------------------------------------------------------


def _resolve_flow_adapter(trial_ctx: Any) -> tuple[Any, RunContext] | None:
    """Return ``(adapter, run_ctx)`` for the active flow run, or ``None``.

    A calibration trial runs exactly one flow process by design; this helper
    returns the first such ``ProcessRun`` it finds along with a freshly
    instantiated ``SolverAdapter`` and a ``RunContext`` whose ``state`` is the
    trial context itself (the adapter reads ``state.execution`` directly).
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


_RUNOFF_WARNING_EMITTED: set[int] = set()


def _add_runoff_to_discharge(
    simulated: pd.Series,
    ctx: Any,
) -> pd.Series:
    """Add the surface-runoff forcing to a baseflow series in m³/s.

    The runoff data manager exposes one or more station time-series in
    ``mm/day`` (per :class:`RunoffConfig` convention). We average the
    stations, resample to the simulated stress-period index, and convert
    to ``m³/s`` using the catchment area read from the geographic
    runtime. When no runoff is loaded, a one-shot warning is emitted and
    the baseflow is returned unchanged.
    """
    runoff = getattr(getattr(ctx, "loaded_data", None), "runoff", None)
    points = getattr(runoff, "points", None) if runoff is not None else None
    if not points:
        ctx_id = id(getattr(ctx, "loaded_data", None))
        if ctx_id not in _RUNOFF_WARNING_EMITTED:
            logger.warning(
                "calibration discharge: no runoff data loaded — comparing "
                "DRN baseflow only against total streamflow observations. "
                "Add 'runoff' to [data.types] for an apples-to-apples fit."
            )
            _RUNOFF_WARNING_EMITTED.add(ctx_id)
        return simulated

    geo = getattr(getattr(ctx, "setup", None), "geographic", None)
    catch_area_km2 = float(getattr(geo, "catch_area", 0.0) or 0.0)
    if catch_area_km2 <= 0.0:
        logger.warning(
            "calibration discharge: catchment area unavailable in setup.geographic; "
            "skipping runoff addition."
        )
        return simulated
    catch_area_m2 = catch_area_km2 * 1e6

    series_list: list[pd.Series] = []
    for rec in points:
        df = getattr(rec, "data", None)
        if df is None or getattr(df, "empty", True):
            continue
        idx = pd.to_datetime(df["datetime"])
        if getattr(idx, "dt", None) is not None and idx.dt.tz is not None:
            idx = idx.dt.tz_localize(None)
        s = pd.Series(df["value"].astype("float64").values, index=pd.DatetimeIndex(idx))
        series_list.append(s)
    if not series_list:
        return simulated

    runoff_mm_per_d = pd.concat(series_list, axis=1).mean(axis=1)
    target_index = simulated.index
    runoff_index = runoff_mm_per_d.index
    if runoff_index.tz is None and target_index.tz is not None:
        runoff_mm_per_d = runoff_mm_per_d.tz_localize(target_index.tz)
    elif runoff_index.tz is not None and target_index.tz is None:
        runoff_mm_per_d = runoff_mm_per_d.tz_localize(None)
    elif runoff_index.tz is not None and target_index.tz is not None:
        runoff_mm_per_d = runoff_mm_per_d.tz_convert(target_index.tz)
    aligned = observed_on_simulation_index(runoff_mm_per_d, pd.DatetimeIndex(target_index))
    runoff_m3_per_s = aligned * 1e-3 * catch_area_m2 / 86400.0
    return simulated.add(runoff_m3_per_s, fill_value=0.0)


# ---------------------------------------------------------------------------
# Time-index resolution
# ---------------------------------------------------------------------------


def _resolve_time_index(ctx: Any, n_timesteps: int = 0) -> pd.DatetimeIndex | None:
    """Build a ``DatetimeIndex`` matching the simulation time grid.

    Returns the stress-period end timestamps. ``n_timesteps`` is kept as
    a hint - when ``> 0`` the index is truncated to that length, otherwise
    the full timeline (``boundaries[1:]``) is returned. ``None`` is
    returned when the simulation's time boundaries are not available so
    callers fall back to a positional series.
    """
    time_grid = getattr(ctx.setup, "time_grid", None)
    if time_grid is None:
        return None
    boundaries = getattr(time_grid, "boundaries", None)
    if not boundaries or len(boundaries) < 2:
        return None
    try:
        end_stamps = list(boundaries[1:])
        if n_timesteps > 0:
            end_stamps = end_stamps[:n_timesteps]
        return pd.DatetimeIndex(pd.to_datetime(end_stamps))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score(observed: pd.Series, simulated: pd.Series, objective: str) -> float:
    """Align both series at the simulation frequency, compute the scalar metric.

    Returns the *cost* (lower is better) - higher-is-better metrics like
    NSE / KGE are flipped into ``1 - value`` so the optimizer always
    minimizes. This matches the convention in ``ScalarObjective``.
    """
    metric = METRICS.get(objective.lower())
    if metric is None:
        raise ValueError(
            f"Unknown calibration objective {objective!r}. "
            f"Choices: {sorted(METRICS)} or a user callable via 'module.path:fn'."
        )
    paired = align_observed_simulated(observed, simulated)
    if paired.empty:
        raise ValueError("No overlapping finite observation/simulation samples for calibration")
    value = float(metric(paired["sim"].values, paired["obs"].values))
    if not np.isfinite(value):
        raise ValueError(f"Calibration metric {objective!r} returned a non-finite value")
    return (1.0 - value) if objective.lower() in HIGHER_IS_BETTER else value


# ---------------------------------------------------------------------------
# Public factory - build a metric_fn bound to the prepared observations
# ---------------------------------------------------------------------------


def build_metric_extractor(
    variable: str | None,
    objective: str | None,
    ctx: Any,
    *,
    outputs: Mapping[str, CalibOutputDecl] | None = None,
    objective_blocks: list[CalibObjectiveBlockDecl] | None = None,
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Return a metric function closed over the loaded observations.

    The returned callable matches the :data:`TrialMetricFn` signature:

    .. code-block:: python

       metric_fn(ctx, *, objective=..., variable=...) -> (primary, metrics)

    ``ctx`` passed at each call is the **trial context** (post-solver),
    while the ``ctx`` captured here is the **base context** (where the
    observations were loaded). They share ``loaded_data`` by reference.

    When ``outputs`` and ``objective_blocks`` are both provided, the
    extractor routes through :func:`build_objective_from_config`: it
    extracts every declared output from the trial context, assembles a
    ``simulated_by_output`` mapping, and the composite objective returns
    the per-block totals as components. Otherwise the legacy single-metric
    path runs against ``loaded_data`` (variable + objective).
    """
    if outputs and objective_blocks:
        return _build_composite_metric_extractor(outputs, objective_blocks)

    observed = _load_observed(ctx, variable) if variable else []
    if not observed:
        logger.warning("No observations for variable=%r.", variable)

    def metric_fn(trial_ctx: Any, *, objective: str = objective, variable: str = variable):
        resolved = _resolve_flow_adapter(trial_ctx)
        if resolved is None:
            raise NotImplementedError("No flow solver adapter available for calibration")
        if not observed:
            raise ValueError(f"No observations available for calibration variable {variable!r}")
        adapter, run_ctx = resolved

        time_idx = _resolve_time_index(trial_ctx, n_timesteps=0)
        try:
            if variable == "discharge":
                simulated = adapter.extract_calibration_series(
                    run_ctx,
                    None,
                    variable="discharge",
                    time_index=time_idx,
                )
                if simulated.empty:
                    raise NotImplementedError(
                        f"Solver {run_ctx.run.solver!r} returned no discharge calibration series"
                    )
                # Add the surface runoff forcing (data layer) to the
                # baseflow component drained by MODFLOW so the simulated
                # signal matches the total streamflow recorded by the
                # observation station.
                simulated = _add_runoff_to_discharge(simulated, trial_ctx)
                components: dict[str, float] = {}
                costs: list[float] = []
                for obs_rec in observed:
                    cost = _score(obs_rec.series, simulated, objective)
                    components[f"{objective}@{obs_rec.station_id}"] = cost
                    if np.isfinite(cost):
                        costs.append(cost)
                if not costs:
                    raise ValueError("No finite discharge calibration costs were produced")
                return float(np.mean(costs)), components

            elif variable == "head":
                # Head calibration needs a station→cell mapping. For now we
                # look it up on the setup.domain if available; Phase 3 will
                # flesh out a dedicated mapper.
                station_cells = _resolve_station_cells(trial_ctx, observed)
                if not station_cells:
                    raise NotImplementedError(
                        "No station-to-cell mapping available for head calibration"
                    )
                components = {}
                costs = []
                for obs_rec in observed:
                    cell = station_cells.get(obs_rec.station_id)
                    if cell is None:
                        continue
                    sim = adapter.extract_calibration_series(
                        run_ctx,
                        None,
                        variable="head",
                        station_cells={obs_rec.station_id: cell},
                        time_index=time_idx,
                    )
                    if sim.empty:
                        raise NotImplementedError(
                            f"Solver {run_ctx.run.solver!r} returned no head calibration series"
                        )
                    cost = _score(obs_rec.series, sim, objective)
                    components[f"{objective}@{obs_rec.station_id}"] = cost
                    if np.isfinite(cost):
                        costs.append(cost)
                if not costs:
                    raise ValueError("No finite head calibration costs were produced")
                return float(np.mean(costs)), components

            else:
                raise NotImplementedError(f"Calibration variable {variable!r} is not supported")
        except Exception:
            logger.exception("Metric extractor failed")
            raise

    return metric_fn


def _resolve_station_cells(
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
                        cell = _find_cell_at_point(ctx, xy[0], xy[1])
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


# ---------------------------------------------------------------------------
# Composite extractor: wire CalibrationConfig.outputs to build_objective_from_config
# ---------------------------------------------------------------------------


def _coerce_length_to_m(value: Any) -> float | None:
    """Pull the magnitude in metres from a pint Quantity or bare number.

    Returns ``None`` when ``value`` is None.
    """
    if value is None:
        return None
    to_m = getattr(value, "to", None)
    if callable(to_m):
        try:
            return float(value.to("m").magnitude)
        except Exception:  # pragma: no cover - defensive: unexpected pint state
            pass
    return float(value)


def _point_xy_from_output(output: CalibOutputDecl) -> tuple[float, float] | None:
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


def _call_extract_calibration_series(
    adapter: Any,
    run_ctx: RunContext,
    *,
    variable: str,
    station_cells: Mapping[str, Any] | None = None,
    boundary_id: str | None = None,
    time_index: pd.DatetimeIndex | None = None,
) -> pd.Series:
    """Call an adapter while enforcing explicit boundary filtering support."""
    kwargs: dict[str, Any] = {
        "variable": variable,
        "time_index": time_index,
    }
    if station_cells is not None:
        kwargs["station_cells"] = station_cells
    if boundary_id is not None:
        signature = inspect.signature(adapter.extract_calibration_series)
        supports_keyword = "boundary_id" in signature.parameters or any(
            param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
        )
        if not supports_keyword:
            raise NotImplementedError(
                f"Solver {run_ctx.run.solver!r} cannot filter calibration boundary_id="
                f"{boundary_id!r}"
            )
        kwargs["boundary_id"] = boundary_id
    return adapter.extract_calibration_series(run_ctx, None, **kwargs)


def _slice_time(values: np.ndarray, time: Any, reducer: str) -> list[float]:
    """Apply ``time`` selector and ``reducer`` to a 1D array of simulated values.

    The current implementation honours the simple ``"all" / "first" / "last"``
    selectors and ``"none" / "mean" / "sum" / "last"`` reducers. List-of-
    timestamps selectors degrade to ``"all"`` at this level (the per-output
    extractor would need a time index; left as a follow-up).
    """
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


def _extract_point(ctx: Any, output: CalibOutputDecl) -> list[float]:
    """Extract a head time series at the (x, y) point declared on ``output``.

    Resolves the closest cell in the structured MODFLOW-NWT grid (layer 0)
    by searching the planar mesh centroids.
    """
    resolved = _resolve_flow_adapter(ctx)
    if resolved is None:
        raise NotImplementedError("No flow solver adapter available for point extraction")
    adapter, run_ctx = resolved

    xy = _point_xy_from_output(output)
    if xy is None:
        raise ValueError("Point calibration output requires x/y or geometry")

    cell = _find_cell_at_point(ctx, xy[0], xy[1])
    if cell is None:
        raise NotImplementedError("Could not map point calibration output to a solver cell")
    sim = _call_extract_calibration_series(
        adapter,
        run_ctx,
        variable="head",
        station_cells={"_pt": cell},
        time_index=None,
    )
    if sim.empty:
        raise NotImplementedError("Solver returned no point calibration series")
    return _slice_time(sim.values, output.time, output.reducer)


def _extract_boundary(ctx: Any, output: CalibOutputDecl) -> list[float]:
    """Extract a boundary time series filtered by ``boundary_id``."""
    resolved = _resolve_flow_adapter(ctx)
    if resolved is None:
        raise NotImplementedError("No flow solver adapter available for boundary extraction")
    adapter, run_ctx = resolved

    sim = _call_extract_calibration_series(
        adapter,
        run_ctx,
        variable="discharge",
        boundary_id=str(output.boundary_id),
        time_index=None,
    )
    if sim.empty:
        raise NotImplementedError("Solver returned no boundary calibration series")
    return _slice_time(sim.values, output.time, output.reducer)


def _extract_cell(ctx: Any, output: CalibOutputDecl) -> list[float]:
    """Extract a head time series at an explicit cell selector."""
    resolved = _resolve_flow_adapter(ctx)
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
    sim = _call_extract_calibration_series(
        adapter,
        run_ctx,
        variable=output.variable,
        station_cells={"_cell": selector},
        time_index=None,
    )
    if sim.empty:
        raise NotImplementedError("Solver returned no cell calibration series")
    return _slice_time(sim.values, output.time, output.reducer)


def _find_cell_at_point(ctx: Any, x: float, y: float) -> tuple[int, int, int] | None:
    """Return the closest ``(layer, row, col)`` to ``(x, y)`` on layer 0.

    Tries two sources, in order:

    1. ``ctx.setup.mesh_planar`` cell centroids (catchment-meshed runs).
    2. The MODFLOW-NWT structured grid (``model.mf.modelgrid``) — this
       fallback covers synthetic grids and any project that goes
       straight from ``[modflownwt.sgrid.planar]`` to the solver
       without building a planar mesh.

    Returns ``None`` when neither source resolves a cell, typically
    MODFLOW 6 or unsupported grids.
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
    """Locate ``(0, row, col)`` on a MODFLOW-NWT structured grid.

    Reads cell-centre coordinates from ``model.mf.modelgrid`` (Flopy's
    ``StructuredGrid``). Returns ``None`` if no MODFLOW-NWT model is
    attached or the grid does not expose ``xcellcenters`` / ``ycellcenters``.
    """
    resolved = _resolve_flow_adapter(ctx)
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


def _build_composite_metric_extractor(
    outputs: Mapping[str, CalibOutputDecl],
    objective_blocks: list[CalibObjectiveBlockDecl],
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Build a metric_fn that routes through ``build_objective_from_config``."""
    cfg_subset = SimpleNamespace(outputs=dict(outputs), objective_blocks=list(objective_blocks))
    composite = build_objective_from_config(cfg_subset)

    def metric_fn(trial_ctx: Any, *, objective: str | None = None, variable: str | None = None):
        del objective, variable
        simulated_by_output: dict[str, list[float]] = {}
        for name, decl in outputs.items():
            try:
                if decl.support == "point":
                    simulated_by_output[name] = _extract_point(trial_ctx, decl)
                elif decl.support == "boundary":
                    simulated_by_output[name] = _extract_boundary(trial_ctx, decl)
                else:
                    simulated_by_output[name] = _extract_cell(trial_ctx, decl)
            except Exception as exc:
                logger.exception("Output %r extraction failed", name)
                raise RuntimeError(
                    f"Output {name!r} extraction failed: {type(exc).__name__}: {exc}"
                ) from exc

        try:
            value = composite.evaluate(simulated_by_output)
        except Exception as exc:
            logger.exception("Composite objective evaluation failed")
            raise RuntimeError(
                f"Composite objective evaluation failed: {type(exc).__name__}: {exc}"
            ) from exc

        components = {key: float(val) for key, val in value.components.items()}
        total = float(value.total)
        return total, components

    return metric_fn


__all__ = ("build_metric_extractor", "ObservedSeries")
