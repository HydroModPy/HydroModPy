"""Point-record discretization on cell centres."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from hydromodpy.core.config_kit.types import InterpolationMethod
from hydromodpy.core.exceptions import DataContractViolation
from hydromodpy.core.time.coverage import enforce_coverage, samples_by_period
from hydromodpy.spatial.forcing.sources import (
    crs_mismatch,
    interpolate_points_on_cells,
    unit_to_m_per_s_factor,
)


def extract_located_points(load_result: Any) -> list[Any]:
    """Return PointRecords that have a valid location with coordinates."""
    result = []
    for rec in load_result.points:
        loc = getattr(rec, "location", None)
        if loc is not None and hasattr(loc, "x") and hasattr(loc, "y"):
            result.append(rec)
    return result


def _variable_of(records: list[Any]) -> str:
    """Return the variable the station *records* hold, as the messages name it."""
    names = sorted({str(getattr(rec, "variable", None) or "forcing") for rec in records})
    return " and ".join(names)


def _refuse_another_crs(located_points: list[Any], mesh_crs: str | None) -> None:
    """Refuse a station whose location is not in the CRS of the mesh.

    A station is never reprojected: its x and y are read as cell coordinates.
    When the location or the mesh declares no CRS that places it on the Earth,
    the two cannot be compared and the station is read as it is.
    """
    for rec in located_points:
        names = crs_mismatch(rec.location.crs, mesh_crs)
        if names is None:
            continue
        station_name, mesh_name = names
        raise DataContractViolation(
            f"The {_variable_of([rec])} station {getattr(rec, 'station_id', '?')} is in "
            f"{station_name} and the mesh in {mesh_name}. A station is never reprojected, so "
            f"each cell would read the value of another place. Give the station coordinates "
            f"in {mesh_name}, or build the mesh in {station_name}."
        )


def period_means(
    series: pd.Series,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]],
    *,
    coverage_policy: str,
    label: str,
    variable: str = "forcing",
) -> np.ndarray:
    """Mean value of a station series in each period, under the coverage rule.

    :mod:`hydromodpy.core.time.coverage` says which samples a period takes and
    what a period the record does not cover becomes. ``variable`` names the
    variable of the series in the messages.
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
        raise ValueError(
            f"Coverage check failed for {variable}: {label} contains non-finite values."
        )
    return values


def discretize_located_points(
    *,
    located_points: list[Any],
    centers: np.ndarray,
    nper: int,
    period_bounds: list[tuple[pd.Timestamp, pd.Timestamp]] | None,
    coverage_policy: str = "ignore",
    method: InterpolationMethod = "nearest",
    source_unit: str = "mm/day",
    mesh_crs: str | None,
    idw_power: float = 2.0,
) -> dict[int, np.ndarray]:
    """Interpolate the time series of located points onto cell centers.

    A station in another CRS than ``mesh_crs`` is refused. ``idw_power`` is the
    exponent of the IDW weights.
    """
    _refuse_another_crs(located_points, mesh_crs)
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
                variable=_variable_of([rec]),
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
            for s, rec in zip(station_series, located_points, strict=True):
                series_values = np.asarray(s.to_numpy(), dtype=float)
                if not np.all(np.isfinite(series_values)):
                    raise ValueError(
                        f"Coverage check failed for {_variable_of([rec])}: point forcing "
                        "contains non-finite values."
                    )
                period_values.append(float(s.mean()))
            values = np.asarray(period_values, dtype=float)

        if not np.all(np.isfinite(values)):
            raise ValueError(
                f"Coverage check failed for {_variable_of(located_points)}: stress period "
                f"{kper} contains non-finite values."
            )

        # Convert from source unit to m/s.  Per-record unit takes precedence
        # over the caller-supplied default so that mixed-unit datasets work.
        unit_factors = np.array(
            [unit_to_m_per_s_factor(getattr(p, "unit", source_unit)) for p in located_points]
        )
        values_m_s = values * unit_factors

        rch_arrays[kper] = interpolate_points_on_cells(
            station_x, station_y, values_m_s, centers, method, idw_power=idw_power
        )

    return rch_arrays
