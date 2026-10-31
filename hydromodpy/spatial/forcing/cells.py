"""Forcing fields and station series on the cells of a mesh.

Converts :class:`LoadResult` field records (xarray, NetCDF, GeoTIFF) and
located point records into one value per cell, in m/s, for every stress
period. This is the only path a solver takes to put a spatial forcing on its
cells, whatever the mesh engine: it reads the cell centres, and the cell
polygons of the planar mesh for the ``"area"`` method, so a regular grid, a
triangulation and a Voronoi dual are served alike.

Every public function is **variable-agnostic** and works with any LoadResult
(recharge, precipitation, ETP, temperature, etc.).

The stress-period bounds live here too. Implementation details are split across:
- ``sources`` - units, dataset variables, interpolation on cell centres,
- ``area_weights`` - area-weighted mean of a grid over the cell polygons,
- ``interpolation`` - nearest, linear and IDW interpolation onto target centres,
- ``rasters`` - xarray + NetCDF + GeoTIFF discretization, and the spatial mean
  of the homogeneous fallback series,
- ``stations`` - located point time-series.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from hydromodpy.core.config_kit.types import InterpolationMethod
from hydromodpy.spatial.forcing.rasters import discretize_one_field_record, spatial_mean_one_field
from hydromodpy.spatial.forcing.sources import refuse_area_for_stations
from hydromodpy.spatial.forcing.stations import (
    discretize_located_points,
    extract_located_points,
)

if TYPE_CHECKING:
    from hydromodpy.core.time import ResolvedSimulationTimeWindow
    from hydromodpy.spatial.mesh.model.hydro_mesh import HydroMesh

__all__ = [
    "discretize_fields_on_cells",
    "discretize_points_on_cells",
    "spatial_mean_from_fields",
    "stress_period_bounds",
]


def stress_period_bounds(
    nper: int,
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> list[tuple[pd.Timestamp, pd.Timestamp]] | None:
    """Return (start, end) bounds for each stress period, or None."""
    if simulation_window is None:
        return None

    explicit_bounds = getattr(simulation_window, "period_bounds", None)
    if explicit_bounds is not None:
        bounds = []
        for raw_start, raw_end in tuple(explicit_bounds)[: int(nper)]:
            bounds.append((pd.Timestamp(raw_start), pd.Timestamp(raw_end)))
        return bounds or None

    from hydromodpy.core.time import build_simulation_time_boundaries

    boundaries = build_simulation_time_boundaries(simulation_window)
    bounds = []
    for i in range(min(nper, len(boundaries) - 1)):
        bounds.append((boundaries[i], boundaries[i + 1]))
    return bounds


def _cell_centers(centers: np.ndarray) -> np.ndarray:
    """Return ``centers`` as an ``(n_cells, 2)`` float array, or refuse it."""
    xy = np.asarray(centers, dtype=float)
    if xy.ndim != 2 or xy.shape[1] != 2:
        raise ValueError(f"centers must have shape (n_cells, 2), got {xy.shape}")
    return xy


def discretize_fields_on_cells(
    *,
    load_result: Any,
    centers: np.ndarray,
    nper: int,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
    method: InterpolationMethod = "nearest",
    mesh: HydroMesh | None = None,
    mesh_crs: str | None,
) -> dict[int, np.ndarray]:
    """Discretize gridded FieldRecords onto the cells of a mesh.

    Each record is averaged in time over every stress period, under the
    coverage rule of :mod:`hydromodpy.core.time.coverage`. When several
    records cover one period, the period takes their mean with equal weights.

    Parameters
    ----------
    load_result:
        LoadResult containing FieldRecords with gridded data. Data units are
        read from each record.
    centers:
        Cell centres ``(n_cells, 2)``, in the CRS of the records.
    nper:
        Number of stress periods in the simulation.
    simulation_window:
        Optional time window for temporal alignment of field data.
    method:
        Spatial interpolation method: ``"nearest"``, ``"linear"`` or ``"idw"``
        read the source at the cell centre; ``"area"`` weighs each pixel by the
        area it shares with the cell, so a rate times the cell area is the
        integral of the grid over the cell.
    mesh:
        Planar mesh whose cells the centres belong to. ``"area"`` reads its
        cell polygons and refuses to run without it.
    mesh_crs:
        CRS of the cells, as the mesh declares it, required so that no caller
        skips the check by forgetting it. A record in another CRS is refused,
        since a grid is never reprojected. When it is None, or when the record
        or the mesh declares no CRS that places it on the Earth (none,
        unreadable, or a local frame), the two cannot be compared and the
        record is read as it is.

    Returns
    -------
    dict[int, np.ndarray]
        Mapping ``{kper: array(n_cells)}`` with values in **m/s**.
    """
    xy = _cell_centers(centers)
    n_cells = xy.shape[0]

    if not load_result.has_fields:
        return {kper: np.zeros(n_cells, dtype=float) for kper in range(nper)}

    period_bounds = stress_period_bounds(nper, simulation_window)
    coverage_policy = str(getattr(simulation_window, "coverage_policy", "ignore"))

    # Several records covering one period are averaged with equal weights:
    # one weight per record, whatever their order or their number.
    sums: dict[int, np.ndarray] = {}
    counts: dict[int, int] = {}
    for field_rec in load_result.fields:
        field_arrays = discretize_one_field_record(
            field_rec,
            centers=xy,
            nper=nper,
            period_bounds=period_bounds,
            coverage_policy=coverage_policy,
            method=method,
            mesh=mesh,
            mesh_crs=mesh_crs,
        )
        for kper, arr in field_arrays.items():
            if kper in sums:
                sums[kper] = sums[kper] + arr
                counts[kper] += 1
            else:
                sums[kper] = np.asarray(arr, dtype=float)
                counts[kper] = 1
    arrays = {kper: sums[kper] / counts[kper] for kper in sums}

    # Fill missing periods with zeros.
    for kper in range(nper):
        if kper not in arrays:
            arrays[kper] = np.zeros(n_cells, dtype=float)

    return arrays


def discretize_points_on_cells(
    *,
    load_result: Any,
    centers: np.ndarray,
    nper: int,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
    method: InterpolationMethod = "nearest",
    source_unit: str = "mm/day",
    mesh_crs: str | None,
    idw_power: float = 2.0,
) -> dict[int, np.ndarray]:
    """Interpolate located PointRecords onto the cell centres of a mesh.

    Requires each PointRecord to carry a ``location`` with (x, y) coordinates.
    Station values are interpolated onto cell centres per stress period.
    ``"area"`` is refused: a station has no pixel to weigh.

    Parameters
    ----------
    load_result:
        LoadResult containing PointRecords with location data.
    centers, nper, simulation_window, method:
        Same as :func:`discretize_fields_on_cells`.
    source_unit:
        Unit of a record that does not state its own.
    mesh_crs:
        Same as :func:`discretize_fields_on_cells`. A station whose location
        is in another CRS is refused, since a station is never reprojected.
    idw_power:
        Exponent of the IDW weights, read by ``"idw"`` only.

    Returns
    -------
    dict[int, np.ndarray]
        Mapping ``{kper: array(n_cells)}`` with values in **m/s**.
    """
    refuse_area_for_stations(method)
    xy = _cell_centers(centers)

    located_points = extract_located_points(load_result)
    if not located_points:
        return {kper: np.zeros(xy.shape[0], dtype=float) for kper in range(nper)}

    return discretize_located_points(
        located_points=located_points,
        centers=xy,
        nper=nper,
        period_bounds=stress_period_bounds(nper, simulation_window),
        coverage_policy=str(getattr(simulation_window, "coverage_policy", "ignore")),
        method=method,
        source_unit=source_unit,
        mesh_crs=mesh_crs,
        idw_power=idw_power,
    )


def spatial_mean_from_fields(load_result: Any) -> pd.Series | None:
    """Compute the spatial mean of FieldRecords to produce a homogeneous series.

    Reduces gridded data (TIF, NC, xarray) to a single scalar per time step
    by averaging the valid pixels: a nodata or NaN pixel is left out, and a
    time step with no valid pixel is refused. Returns a pandas Series in
    mm/day (data-manager internal unit) or None if no fields are available.
    """
    if not load_result.has_fields:
        return None

    all_series: list[pd.Series] = []
    for field_rec in load_result.fields:
        s = spatial_mean_one_field(field_rec)
        if s is not None:
            all_series.append(s)

    if not all_series:
        return None

    if len(all_series) == 1:
        return all_series[0]

    combined = pd.concat(all_series, axis=1)
    return combined.mean(axis=1)
