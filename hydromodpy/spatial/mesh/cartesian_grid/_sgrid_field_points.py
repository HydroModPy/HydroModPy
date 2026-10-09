"""Point-record discretization on structured grids."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.config_kit.types import InterpolationMethod
from hydromodpy.core.time.coverage import enforce_coverage, samples_by_period


def extract_located_points(load_result: Any) -> list[Any]:
    """Return PointRecords that have a valid location with coordinates."""
    result = []
    for rec in load_result.points:
        loc = getattr(rec, "location", None)
        if loc is not None and hasattr(loc, "x") and hasattr(loc, "y"):
            result.append(rec)
    return result


def period_means(
    series: pd.Series,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]],
    *,
    coverage_policy: str,
    label: str,
) -> np.ndarray:
    """Mean value of a station series in each period, under the coverage rule.

    :mod:`hydromodpy.core.time.coverage` says which samples a period takes and
    what a period the record does not cover becomes.
    """
    data = series.sort_index()
    boundaries = [period_bounds[0][0], *(end for _, end in period_bounds)]
    periods = samples_by_period(data.index, boundaries)
    enforce_coverage(periods, boundaries, policy=coverage_policy, label=label)
    samples = np.asarray(data.to_numpy(), dtype=float)
    values = np.asarray(
        [
            float(samples[inside].mean()) if inside.size else float(samples[int(fill)])
            for inside, fill in zip(periods.inside, periods.fill, strict=True)
        ],
        dtype=float,
    )
    if not np.all(np.isfinite(values)):
        raise ValueError(f"Recharge coverage check failed: {label} contains non-finite values.")
    return values


def discretize_located_points(
    *,
    located_points: list[Any],
    x_centers: np.ndarray,
    y_centers: np.ndarray,
    nrow: int,
    ncol: int,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    coverage_policy: str = "ignore",
    method: InterpolationMethod = "nearest",
    source_unit: str = "mm/day",
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

    station_periods: list[np.ndarray] | None = None
    if period_bounds is not None:
        station_periods = [
            period_means(
                s,
                list(period_bounds),
                coverage_policy=coverage_policy,
                label=f"The point forcing record of station {getattr(rec, 'station_id', '?')}",
            )
            for s, rec in zip(station_series, located_points, strict=True)
        ]

    rch_arrays: dict[int, np.ndarray] = {}
    for kper in range(nper):
        # Get the value of each station for this period.
        if station_periods is not None and kper < len(period_bounds):
            values = np.array([periods[kper] for periods in station_periods])
        else:
            # No temporal alignment: use full-series mean.
            period_values: list[float] = []
            for s in station_series:
                series_values = np.asarray(s.to_numpy(), dtype=float)
                if not np.all(np.isfinite(series_values)):
                    raise ValueError(
                        "Recharge coverage check failed: point forcing contains non-finite values."
                    )
                period_values.append(float(s.mean()))
            values = np.asarray(period_values, dtype=float)

        if not np.all(np.isfinite(values)):
            raise ValueError(
                f"Recharge coverage check failed: stress period {kper} contains non-finite values."
            )

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
