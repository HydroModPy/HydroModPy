"""Series helpers: observation loading, time-index resolution, runoff postprocess.

These primitives massage time series into shapes the scalar/composite scorers
expect. They do not call the solver layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from hydromodpy.core.logging import get_logger
from hydromodpy.results.time_alignment import observed_on_simulation_index

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ObservedSeries:
    """One observed timeseries indexed by time."""

    station_id: str
    variable: str
    series: pd.Series


def load_observed(ctx: Any, variable: str) -> list[ObservedSeries]:
    """Pull observation timeseries from the loaded-data context.

    ``variable`` is the calibration-target variable (``"discharge"``,
    ``"head"``, ``"lake_level"``). Discharge comes from ``hydrometry``, head
    from ``piezometry``, lake level from ``lake_levels``. Returns one
    ``ObservedSeries`` per station so multi-station calibration works uniformly.
    """
    field_name = {
        "discharge": "hydrometry",
        "head": "piezometry",
        "lake_level": "lake_levels",
    }.get(variable)
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


def resolve_time_index(ctx: Any, n_timesteps: int = 0) -> pd.DatetimeIndex | None:
    """Build a ``DatetimeIndex`` matching the simulation time grid.

    Returns the stress-period end timestamps. ``n_timesteps > 0`` truncates the
    index. ``None`` is returned when boundaries are not available so callers
    fall back to a positional series.
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


_RUNOFF_WARNING_EMITTED: set[int] = set()


def add_runoff_to_discharge(simulated: pd.Series, ctx: Any) -> pd.Series:
    """Add the surface-runoff forcing to a baseflow series in m³/s.

    The runoff data manager exposes one or more station time-series in
    ``mm/day``. Stations are averaged, resampled to the simulated stress-period
    index, and converted to ``m³/s`` using the catchment area read from the
    geographic runtime. When no runoff is loaded, a one-shot warning is
    emitted and the baseflow is returned unchanged.
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


__all__ = [
    "ObservedSeries",
    "load_observed",
    "resolve_time_index",
    "add_runoff_to_discharge",
]
