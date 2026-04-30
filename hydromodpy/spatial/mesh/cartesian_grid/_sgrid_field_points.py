"""Point-record discretization on structured grids."""

from __future__ import annotations

from typing import Any, Literal

import numpy as np
import pandas as pd

InterpolationMethod = Literal["nearest", "linear", "idw"]


def extract_located_points(load_result: Any) -> list[Any]:
    """Return PointRecords that have a valid location with coordinates."""
    result = []
    for rec in load_result.points:
        loc = getattr(rec, "location", None)
        if loc is not None and hasattr(loc, "x") and hasattr(loc, "y"):
            result.append(rec)
    return result


def period_mean(series: pd.Series, t_start: pd.Timestamp, t_end: pd.Timestamp) -> float:
    """Mean value of a series within [t_start, t_end)."""
    mask = (series.index >= t_start) & (series.index < t_end)
    subset = series[mask]
    if subset.empty:
        # Fallback: nearest time step.
        diffs = np.abs((series.index - t_start).total_seconds())
        return float(series.iloc[int(np.argmin(diffs))])
    return float(subset.mean())


def discretize_located_points(
    *,
    located_points: list[Any],
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    nrow: int,
    ncol: int,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    method: InterpolationMethod,
    source_unit: str,
) -> dict[int, np.ndarray]:
    """Interpolate the time series of located points onto cell centers."""
    from hydromodpy.spatial.mesh.cartesian_grid._sgrid_field_grid_utils import (
        unit_to_m_per_s_factor,
    )
    from hydromodpy.spatial.mesh.cartesian_grid.spatial_interpolation import (
        interpolate_points_to_grid,
    )

    station_x = np.array([p.location.x for p in located_points])
    station_y = np.array([p.location.y for p in located_points])

    # Build a time series per station (mm/day).
    station_series: list[pd.Series] = []
    for rec in located_points:
        s = rec.data.set_index("datetime")["value"].sort_index().astype(float)
        station_series.append(s)

    rch_arrays: dict[int, np.ndarray] = {}
    for kper in range(nper):
        # Get the value of each station for this period.
        if period_bounds is not None and kper < len(period_bounds):
            t_start, t_end = period_bounds[kper]
            values = np.array([period_mean(s, t_start, t_end) for s in station_series])
        else:
            # No temporal alignment: use full-series mean.
            values = np.array([float(s.mean()) for s in station_series])

        # Convert from source unit to m/s.  Per-record unit takes precedence
        # over the caller-supplied default so that mixed-unit datasets work.
        unit_factors = np.array(
            [unit_to_m_per_s_factor(getattr(p, "unit", source_unit)) for p in located_points]
        )
        values_m_s = values * unit_factors

        arr = interpolate_points_to_grid(
            point_x=station_x,
            point_y=station_y,
            point_values=values_m_s,
            target_x=x_centers,
            target_y=y_centers,
            nrow=nrow,
            ncol=ncol,
            method=method,
        )
        rch_arrays[kper] = arr

    return rch_arrays
