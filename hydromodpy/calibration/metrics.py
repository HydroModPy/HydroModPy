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

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.calibration.objective import HIGHER_IS_BETTER, METRICS

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


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


def _extract_discharge_modflownwt(
    output_dir: Path,
    model_name: str,
    time_index: pd.DatetimeIndex | None = None,
) -> pd.Series | None:
    """Sum the DRAIN/DRN budget component per timestep and return a series.

    MODFLOW-NWT writes DRN outflow as negative values in the CBC file;
    we sum their absolute values cell-wise, layer-wise, per timestep,
    giving the catchment-outlet discharge in the native MODFLOW volume-
    per-time units (m³/d on a metric-day grid).
    """
    import flopy.utils.binaryfile as bf

    cbc_path = output_dir / f"{model_name}.cbc"
    if not cbc_path.exists():
        # Some workflows use ``.cbb``
        cbc_path = output_dir / f"{model_name}.cbb"
    if not cbc_path.exists():
        logger.debug("CBC file not found in %s", output_dir)
        return None

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


def _resolve_time_index(ctx: Any, n_timesteps: int) -> pd.DatetimeIndex | None:
    """Build a ``DatetimeIndex`` matching the simulation time grid.

    Falls back to ``None`` when the simulation's time boundaries are not
    available (callers then receive a positional series).
    """
    time_grid = getattr(ctx.setup, "time_grid", None)
    if time_grid is None:
        return None
    boundaries = getattr(time_grid, "boundaries", None)
    if not boundaries or len(boundaries) < 2:
        return None
    # Time grid boundaries are the stress-period edges; MODFLOW-NWT writes
    # one value per stress-period end by default.
    try:
        # Use the interior endpoints (first boundary is t=0 / pre-simulation).
        return pd.DatetimeIndex(pd.to_datetime(list(boundaries[1 : n_timesteps + 1])))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _score(observed: pd.Series, simulated: pd.Series, objective: str) -> float:
    """Align two series on the observed index and compute the scalar metric.

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
    # Align to the observed index - MODFLOW may emit at different stamps.
    sim_aligned = sim.reindex(obs.index, method="nearest", tolerance=pd.Timedelta(days=31))
    value = float(metric(obs.values, sim_aligned.values))
    if np.isnan(value):
        return float("nan")
    return (1.0 - value) if objective.lower() in HIGHER_IS_BETTER else value


# ---------------------------------------------------------------------------
# Public factory - build a metric_fn bound to the prepared observations
# ---------------------------------------------------------------------------


def build_metric_extractor(
    variable: str,
    objective: str,
    ctx: Any,
) -> Callable[..., tuple[float, Mapping[str, float]]]:
    """Return a metric function closed over the loaded observations.

    The returned callable matches the :data:`TrialMetricFn` signature:

    .. code-block:: python

       metric_fn(ctx, *, objective=..., variable=...) -> (primary, metrics)

    ``ctx`` passed at each call is the **trial context** (post-solver),
    while the ``ctx`` captured here is the **base context** (where the
    observations were loaded). They share ``loaded_data`` by reference.
    """
    observed = _load_observed(ctx, variable)
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


__all__ = ("build_metric_extractor", "ObservedSeries")
