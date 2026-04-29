"""RAM metric extraction for lightweight calibration trials.

During a calibration loop, each trial runs in ``lightweight`` mode: the
solver still writes its binary output (``.hds``, ``.cbc``, ...) to the
workspace scratch folder, but no Zarr / Parquet / catalog rows are
created. The optimizer only needs a scalar objective value to drive the
ask/tell loop - the metric extractor in this module reads the solver
binaries directly, aligns the simulated series with the observations
that were loaded once during ``prepare_trials``, and returns a
``(primary_metric, per_component_metrics)`` tuple.

Current coverage:

- **MODFLOW-NWT** - discharge (DRAIN budget summed over the catchment)
  and head at observation points (read from the ``.hds`` file).

MODFLOW-6 and other solvers are scheduled for a follow-up: the
extractor returns ``(nan, {})`` for unsupported solvers so the trial
reports ``status="completed"`` but its objective becomes ``nan`` and
the optimizer naturally skips it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
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
# Simulated series extraction (solver-specific)
# ---------------------------------------------------------------------------


def _find_flow_run(ctx: Any) -> tuple[str, Any, Path] | None:
    """Return ``(run_id, model, output_dir)`` for the first flow run, else None.

    The calibration trial runs one flow process by design, so we return
    the earliest entry in ``models_by_run_id``. ``output_dir`` is pulled
    from ``output_dirs_by_run_id`` (populated by ``SimulationRunner``)
    and falls back to the model's ``full_path`` attribute when absent.
    """
    registry = getattr(ctx, "execution", None)
    if registry is None:
        return None
    models = registry.models_by_run_id or {}
    output_dirs = getattr(registry, "output_dirs_by_run_id", {}) or {}
    if not models:
        return None

    # Pick the first flow run (process_type == "flow").
    plan = registry.simulation_plan
    flow_run_id = None
    if plan is not None:
        for run in plan.runs:
            if run.process_type == "flow" and run.id in models:
                flow_run_id = run.id
                break
    if flow_run_id is None:
        flow_run_id = next(iter(models))

    model = models[flow_run_id]
    output_dir = output_dirs.get(flow_run_id)
    if output_dir is None:
        full_path = getattr(model, "full_path", None)
        if full_path is not None:
            output_dir = Path(full_path)
    if output_dir is None:
        return None
    return flow_run_id, model, Path(output_dir)


# MODFLOW ITMUNI codes -> seconds per native time unit. Used to convert
# the CBC native flux unit (e.g. m³/d when itmuni=4) into m³/s before
# comparing against observations stored in m³/s.
_ITMUNI_TO_SECONDS: dict[int, float] = {
    0: 1.0,  # undefined -> treat as seconds
    1: 1.0,  # seconds
    2: 60.0,  # minutes
    3: 3600.0,  # hours
    4: 86400.0,  # days
    5: 31557600.0,  # years (365.25 days)
}


def _read_itmuni_from_dis(dis_path: Path) -> int:
    """Return the ITMUNI integer declared in a MODFLOW DIS file.

    Falls back to ``1`` (seconds) when the file is missing or the second
    header line cannot be parsed.
    """
    if not dis_path.is_file():
        return 1
    try:
        with dis_path.open("r", encoding="utf-8") as fh:
            header_lines: list[str] = []
            for raw in fh:
                stripped = raw.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                header_lines.append(stripped)
                if len(header_lines) >= 2:
                    break
        if len(header_lines) < 2:
            return 1
        tokens = header_lines[1].split()
        if len(tokens) >= 2:
            return int(tokens[1])
    except (OSError, ValueError):
        return 1
    return 1


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


def _extract_discharge_modflownwt(
    output_dir: Path,
    model_name: str,
    time_index: pd.DatetimeIndex | None = None,
) -> pd.Series | None:
    """Sum the DRAIN/DRN budget component per timestep and return a series.

    MODFLOW-NWT writes DRN outflow as negative values in the CBC file;
    we sum their absolute values cell-wise, layer-wise, per timestep,
    then convert from the run's native time unit (per ITMUNI in the DIS
    file) to ``m³/s`` so the result is directly comparable to the
    hydrometry observations (which are always normalised to m³/s).
    """
    import flopy.utils.binaryfile as bf

    cbc_path = output_dir / f"{model_name}.cbc"
    if not cbc_path.exists():
        # Some workflows use ``.cbb``
        cbc_path = output_dir / f"{model_name}.cbb"
    if not cbc_path.exists():
        logger.debug("CBC file not found in %s", output_dir)
        return None

    itmuni = _read_itmuni_from_dis(output_dir / f"{model_name}.dis")
    seconds_per_unit = _ITMUNI_TO_SECONDS.get(itmuni, 1.0)

    cbb = bf.CellBudgetFile(str(cbc_path))
    try:
        record_names = [r.decode().strip() for r in cbb.get_unique_record_names()]
        drain_key = next(
            (key for key in record_names if key.lower() in {"drains", "drn", "drain"}),
            None,
        )
        if drain_key is None:
            logger.debug("No DRAIN component in CBC; components were %s", record_names)
            return None

        times = cbb.get_times()
        kstpkpers = cbb.get_kstpkper()
        n_timesteps = len(times)
        values = np.zeros(n_timesteps, dtype=float)
        for t, (time, ksk) in enumerate(zip(times, kstpkpers, strict=False)):
            try:
                data = cbb.get_data(text=drain_key, kstpkper=ksk, totim=time, full3D=True)
            except Exception:
                continue
            if not data:
                continue
            arr = np.asarray(data[0], dtype=float)
            values[t] = float(np.abs(np.minimum(arr, 0.0)).sum())
    finally:
        cbb.close()

    # Native MODFLOW flux is volume / itmuni-time-unit. Divide by the
    # number of seconds in that unit to obtain m³/s.
    values = values / seconds_per_unit

    if time_index is not None and len(time_index) == n_timesteps:
        return pd.Series(values, index=time_index, name="discharge")
    return pd.Series(values, name="discharge")


def _extract_head_modflownwt(
    output_dir: Path,
    model_name: str,
    *,
    station_cells: Mapping[str, tuple[int, int, int]],
    time_index: pd.DatetimeIndex | None = None,
) -> dict[str, pd.Series]:
    """Return head timeseries keyed by station at the given ``(k, i, j)`` cells."""
    import flopy.utils.binaryfile as bf

    hds_path = output_dir / f"{model_name}.hds"
    if not hds_path.exists():
        logger.debug("HDS file not found in %s", output_dir)
        return {}

    hf = bf.HeadFile(str(hds_path))
    try:
        times = hf.get_times()
        n_t = len(times)
        out: dict[str, pd.Series] = {}
        # Cache full heads by timestep to avoid re-reading the file per station.
        for station_id, (k, i, j) in station_cells.items():
            values = np.full(n_t, np.nan, dtype=float)
            for t, totim in enumerate(times):
                try:
                    head = hf.get_data(totim=totim)
                    values[t] = float(head[k, i, j])
                except Exception:
                    pass
            # Treat HDRY / HNOFLO sentinels as NaN (same thresholds as extractor)
            values[np.abs(values) > 1e6] = np.nan
            if time_index is not None and len(time_index) == n_t:
                out[station_id] = pd.Series(values, index=time_index, name=f"head@{station_id}")
            else:
                out[station_id] = pd.Series(values, name=f"head@{station_id}")
    finally:
        hf.close()
    return out


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
        return float("nan")
    value = float(metric(paired["sim"].values, paired["obs"].values))
    if np.isnan(value):
        return float("nan")
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
        logger.warning(
            "No observations for variable=%r; metric extractor will return NaN.",
            variable,
        )

    def metric_fn(trial_ctx: Any, *, objective: str = objective, variable: str = variable):
        found = _find_flow_run(trial_ctx)
        if found is None or not observed:
            return float("nan"), {}
        run_id, model, output_dir = found
        model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
        if model_name is None:
            return float("nan"), {}

        time_idx = _resolve_time_index(trial_ctx, n_timesteps=0)
        try:
            if variable == "discharge":
                simulated = _extract_discharge_modflownwt(output_dir, model_name, time_idx)
                if simulated is None:
                    return float("nan"), {}
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
                    if not np.isnan(cost):
                        costs.append(cost)
                if not costs:
                    return float("nan"), components
                return float(np.mean(costs)), components

            elif variable == "head":
                # Head calibration needs a station→cell mapping. For now we
                # look it up on the setup.domain if available; Phase 3 will
                # flesh out a dedicated mapper.
                station_cells = _resolve_station_cells(trial_ctx, observed)
                if not station_cells:
                    return float("nan"), {}
                sim_series = _extract_head_modflownwt(
                    output_dir, model_name, station_cells=station_cells, time_index=time_idx
                )
                components = {}
                costs = []
                for obs_rec in observed:
                    if obs_rec.station_id not in sim_series:
                        continue
                    cost = _score(obs_rec.series, sim_series[obs_rec.station_id], objective)
                    components[f"{objective}@{obs_rec.station_id}"] = cost
                    if not np.isnan(cost):
                        costs.append(cost)
                if not costs:
                    return float("nan"), components
                return float(np.mean(costs)), components

            else:
                logger.warning(
                    "Calibration variable %r not supported yet (add a branch here).",
                    variable,
                )
                return float("nan"), {}
        except Exception as exc:
            logger.exception("Metric extractor failed")
            return float("nan"), {"error": -1.0, "__error__": str(exc)}  # type: ignore[return-value]

    return metric_fn


def _resolve_station_cells(
    ctx: Any,
    observed: list[ObservedSeries],
) -> dict[str, tuple[int, int, int]]:
    """Best-effort station → ``(layer, row, col)`` mapping.

    Reads lat/lon from the station metadata and intersects with the
    model grid when available. Returns an empty dict when the mapping
    cannot be resolved - head calibration then degrades to NaN which
    the optimizer will skip.
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
    by searching the planar mesh centroids. When the trial context does
    not expose a structured grid (MODFLOW 6 / unsupported solver) or the
    ``.hds`` file is missing, returns ``[nan]`` so callers can keep
    operating without crashing.
    """
    found = _find_flow_run(ctx)
    if found is None:
        return [float("nan")]
    _run_id, model, output_dir = found
    model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
    if model_name is None:
        return [float("nan")]

    x_m = _coerce_length_to_m(output.x)
    y_m = _coerce_length_to_m(output.y)
    if x_m is None or y_m is None:
        return [float("nan")]

    cell = _find_cell_at_point(ctx, x_m, y_m)
    if cell is None:
        return [float("nan")]
    series = _extract_head_modflownwt(
        output_dir,
        model_name,
        station_cells={"_pt": cell},
        time_index=None,
    )
    sim = series.get("_pt")
    if sim is None or sim.size == 0:
        return [float("nan")]
    return _slice_time(sim.values, output.time, output.reducer)


def _extract_boundary(ctx: Any, output: CalibOutputDecl) -> list[float]:
    """Extract a boundary time series filtered by ``boundary_id``.

    The current implementation reuses the catchment-wide DRAIN summation
    in :func:`_extract_discharge_modflownwt` and is solver-specific to
    MODFLOW-NWT. Filtering by named boundary id requires a boundname-
    aware reader; left as a follow-up. Returns ``[nan]`` when the CBC
    file is absent.
    """
    found = _find_flow_run(ctx)
    if found is None:
        return [float("nan")]
    _run_id, model, output_dir = found
    model_name = getattr(model, "model_name", None) or getattr(model, "name", None)
    if model_name is None:
        return [float("nan")]

    sim = _extract_discharge_modflownwt(output_dir, model_name, time_index=None)
    if sim is None or sim.size == 0:
        return [float("nan")]
    return _slice_time(sim.values, output.time, output.reducer)


def _extract_cell(ctx: Any, output: CalibOutputDecl) -> list[float]:
    """Extract a head time series at a structured (row, col) cell.

    The current schema does not expose ``row`` / ``col`` explicitly on
    :class:`CalibOutputDecl` (twin benchmarks pass ``support="cell"`` to
    bypass coordinate lookup). Returns ``[nan]`` until the schema gains
    explicit indices; the API entry point is in place for callers that
    pre-resolve a cell elsewhere.
    """
    del ctx, output
    return [float("nan")]


def _find_cell_at_point(ctx: Any, x: float, y: float) -> tuple[int, int, int] | None:
    """Return the closest ``(layer, row, col)`` to ``(x, y)`` on layer 0.

    Tries two sources, in order:

    1. ``ctx.setup.mesh_planar`` cell centroids (catchment-meshed runs).
    2. The MODFLOW-NWT structured grid (``model.mf.modelgrid``) — this
       fallback covers synthetic grids and any project that goes
       straight from ``[modflownwt.sgrid.planar]`` to the solver
       without building a planar mesh.

    Returns ``None`` (caller emits NaN) when neither source resolves a
    cell — typically MODFLOW 6 / unsupported grids.
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
    found = _find_flow_run(ctx)
    if found is None:
        return None
    _run_id, model, _output_dir = found
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
                return float("nan"), {"__error__": f"{type(exc).__name__}: {exc}"}

        try:
            value = composite.evaluate(simulated_by_output)
        except Exception as exc:
            logger.exception("Composite objective evaluation failed")
            return float("nan"), {"__error__": f"{type(exc).__name__}: {exc}"}

        components = {key: float(val) for key, val in value.components.items()}
        total = float(value.total)
        return total, components

    return metric_fn


__all__ = ("build_metric_extractor", "ObservedSeries")
