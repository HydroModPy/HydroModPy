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
    aligned = runoff_mm_per_d.reindex(target_index, method="nearest")
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


def _median_step(index: pd.DatetimeIndex) -> pd.Timedelta | None:
    """Return the median spacing of a datetime index, or ``None`` when undefined."""
    if len(index) < 2:
        return None
    deltas = index.to_series().diff().dropna()
    if deltas.empty:
        return None
    return pd.Timedelta(deltas.median())


def _align_to_simulation_step(obs: pd.Series, sim: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Match obs and sim on the simulation stress-period index.

    The observed series is typically daily while the simulated series is
    one value per stress period (e.g. monthly). Comparing them at the
    daily index would broadcast each monthly sim value 30 times and bias
    every metric. Instead we group obs into bins centered on the sim
    timestamps and take the mean of every observation falling in the
    bin. The simulated series stays at its native sampling.
    """
    if sim.empty or obs.empty:
        return obs, sim

    sim = sim.sort_index()
    obs = obs.sort_index()

    # Restrict obs to the simulated window.
    obs = obs.loc[sim.index.min() : sim.index.max()]
    if obs.empty:
        return obs, sim

    sim_step = _median_step(sim.index)
    obs_step = _median_step(obs.index)
    if sim_step is None or obs_step is None or sim_step <= obs_step:
        # Nothing to bin (irregular index or sim is not coarser than obs).
        sim_aligned = sim.reindex(obs.index, method="nearest", tolerance=sim_step)
        return obs, sim_aligned

    # Bin obs around each sim timestamp. Each sim point t covers
    # [t - sim_step/2, t + sim_step/2). Use ``cut`` over the half-step
    # boundaries derived from the simulation index.
    half = sim_step / 2
    bin_edges = pd.DatetimeIndex([sim.index[0] - half] + [t + half for t in sim.index])
    binned = pd.cut(obs.index, bins=bin_edges, right=False)
    obs_aligned = obs.groupby(binned, observed=True).mean()
    obs_aligned.index = sim.index[: len(obs_aligned)]
    return obs_aligned, sim.loc[obs_aligned.index]


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
    obs = observed.astype(float)
    sim = simulated.astype(float)
    obs_aligned, sim_aligned = _align_to_simulation_step(obs, sim)
    paired = pd.concat([obs_aligned.rename("obs"), sim_aligned.rename("sim")], axis=1).dropna()
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
    """Best-effort station → ``(layer, row, col)`` mapping.

    Reads lat/lon from the station metadata and intersects with the
    model grid when available. Returns an empty dict when the mapping
    cannot be resolved.
    """
    domain = getattr(ctx.setup, "domain", None)
    mesh = getattr(ctx.setup, "mesh_planar", None)
    if mesh is None or domain is None:
        return {}
    # The real mapping lives in hydromodpy.data.variables.piezometry.* -
    # we look up the station record directly from ctx.loaded_data.piezometry
    # to avoid duplicating geometry logic here.
    piezo = getattr(ctx.loaded_data, "piezometry", None)
    if piezo is None:
        return {}
    points = getattr(piezo, "points", None) or []
    cells: dict[str, tuple[int, int, int]] = {}
    for obs_rec in observed:
        for rec in points:
            if str(rec.station_id) == obs_rec.station_id:
                cell = getattr(rec, "cell_ij", None) or getattr(rec, "cell", None)
                if cell is not None and len(cell) >= 2:
                    layer = int(cell[2]) if len(cell) >= 3 else 0
                    cells[obs_rec.station_id] = (layer, int(cell[0]), int(cell[1]))
                break
    return cells


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

    x_m = _coerce_length_to_m(output.x)
    y_m = _coerce_length_to_m(output.y)
    if x_m is None or y_m is None:
        raise ValueError("Point calibration output requires x and y")

    cell = _find_cell_at_point(ctx, x_m, y_m)
    if cell is None:
        raise NotImplementedError("Could not map point calibration output to a solver cell")
    sim = adapter.extract_calibration_series(
        run_ctx,
        None,
        variable="head",
        station_cells={"_pt": cell},
        time_index=None,
    )
    if sim.empty:
        raise NotImplementedError("Solver returned no point calibration series")
    return _slice_time(sim.values, output.time, output.reducer)


def _extract_boundary(ctx: Any, output: CalibOutputDecl) -> list[float]:
    """Extract a boundary time series filtered by ``boundary_id``.

    The current implementation reuses the catchment-wide DRAIN summation
    exposed by ``SolverAdapter.extract_calibration_series(variable="discharge")``.
    Filtering by named boundary id requires a boundname-aware reader.
    """
    resolved = _resolve_flow_adapter(ctx)
    if resolved is None:
        raise NotImplementedError("No flow solver adapter available for boundary extraction")
    adapter, run_ctx = resolved

    sim = adapter.extract_calibration_series(
        run_ctx,
        None,
        variable="discharge",
        time_index=None,
    )
    if sim.empty:
        raise NotImplementedError("Solver returned no boundary calibration series")
    return _slice_time(sim.values, output.time, output.reducer)


def _extract_cell(ctx: Any, output: CalibOutputDecl) -> list[float]:
    """Extract a head time series at a structured (row, col) cell.

    ``support="cell"`` uses explicit structured indices and therefore
    bypasses point-to-cell lookup.
    """
    if output.row is None or output.col is None:
        raise NotImplementedError("Cell calibration outputs require explicit row/column schema")
    resolved = _resolve_flow_adapter(ctx)
    if resolved is None:
        raise NotImplementedError("No flow solver adapter available for cell extraction")
    adapter, run_ctx = resolved
    sim = adapter.extract_calibration_series(
        run_ctx,
        None,
        variable=output.variable,
        station_cells={"_cell": (int(output.layer), int(output.row), int(output.col))},
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
