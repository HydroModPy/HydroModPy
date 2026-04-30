"""Field discretization on structured grids (any 2-D climatic variable).

Converts :class:`LoadResult` field records (xarray, NetCDF, GeoTIFF) and
located point records into per-cell 2-D arrays aligned with the MODFLOW
structured grid.

Every public function is **variable-agnostic** and works with any LoadResult
(recharge, precipitation, ETP, temperature, etc.).

Implementation details are split across:
- ``_sgrid_field_grid_utils`` - cell centers, time bounds, units, interp,
- ``_sgrid_field_xarray`` - xarray + NetCDF + GeoTIFF discretization,
- ``_sgrid_field_points`` - located point time-series,
- ``_sgrid_field_spatial_mean`` - homogeneous fallback series.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pandas as pd

from hydromodpy.spatial.mesh.cartesian_grid._sgrid_field_grid_utils import (
    cell_centers_from_sgrid,
    stress_period_bounds,
)
from hydromodpy.spatial.mesh.cartesian_grid._sgrid_field_points import (
    discretize_located_points,
    extract_located_points,
)
from hydromodpy.spatial.mesh.cartesian_grid._sgrid_field_spatial_mean import (
    spatial_mean_one_field,
)
from hydromodpy.spatial.mesh.cartesian_grid._sgrid_field_xarray import (
    discretize_one_field_record,
)

if TYPE_CHECKING:
    from hydromodpy.core.time import ResolvedSimulationTimeWindow

InterpolationMethod = Literal["nearest", "linear", "idw"]

__all__ = (
    "InterpolationMethod",
    "discretize_fields_on_sgrid",
    "discretize_points_on_sgrid",
    "spatial_mean_from_fields",
)


def discretize_fields_on_sgrid(
    *,
    load_result: Any,
    sgrid: object,
    nper: int,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
    method: InterpolationMethod = "nearest",
) -> dict[int, np.ndarray]:
    """Discretize gridded FieldRecords onto a structured MODFLOW grid.

    Parameters
    ----------
    load_result:
        LoadResult containing FieldRecords with gridded recharge data.
        Data units are assumed to be mm/day (data-manager internal unit).
    sgrid:
        Structured grid object providing nrow, ncol, vertex coordinates.
        Accepts both FloPy ``StructuredGrid`` and ``SolverMesh``.
    nper:
        Number of stress periods in the simulation.
    simulation_window:
        Optional time window for temporal alignment of field data.
    method:
        Spatial interpolation method: ``"nearest"``, ``"linear"``, or ``"idw"``.

    Returns
    -------
    dict[int, np.ndarray]
        Mapping ``{kper: array(nrow, ncol)}`` with values in **m/s**
        (consistent with the homogeneous recharge bridge output).
    """
    nrow = int(sgrid.nrow)
    ncol = int(sgrid.ncol)

    if not load_result.has_fields:
        return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(nper)}

    # Build target cell-center coordinates from the solver grid.
    x_centers, y_centers = cell_centers_from_sgrid(sgrid, nrow, ncol)

    # Compute stress-period boundaries for temporal slicing.
    period_bounds = stress_period_bounds(nper, simulation_window)

    # Aggregate all FieldRecords into one temporal-spatial stack.
    rch_arrays: dict[int, np.ndarray] = {}
    for field_rec in load_result.fields:
        field_arrays = discretize_one_field_record(
            field_rec,
            x_centers=x_centers,
            y_centers=y_centers,
            nrow=nrow,
            ncol=ncol,
            nper=nper,
            period_bounds=period_bounds,
            method=method,
        )
        for kper, arr in field_arrays.items():
            if kper in rch_arrays:
                # Average when multiple records cover the same period.
                rch_arrays[kper] = 0.5 * (rch_arrays[kper] + arr)
            else:
                rch_arrays[kper] = arr

    # Fill missing periods with zeros.
    for kper in range(nper):
        if kper not in rch_arrays:
            rch_arrays[kper] = np.zeros((nrow, ncol), dtype=float)

    return rch_arrays


def discretize_points_on_sgrid(
    *,
    load_result: Any,
    sgrid: object,
    nper: int,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
    method: InterpolationMethod = "nearest",
    source_unit: str = "mm/day",
) -> dict[int, np.ndarray]:
    """Interpolate located PointRecords onto a structured MODFLOW grid.

    Requires each PointRecord to carry a ``location`` with (x, y) coordinates.
    Station values are interpolated onto cell centers per stress period.

    Parameters
    ----------
    load_result:
        LoadResult containing PointRecords with location data.
    sgrid, nper, simulation_window, method:
        Same as :func:`discretize_fields_on_sgrid`.

    Returns
    -------
    dict[int, np.ndarray]
        Mapping ``{kper: array(nrow, ncol)}`` with values in **m/s**.
    """
    nrow = int(sgrid.nrow)
    ncol = int(sgrid.ncol)

    located_points = extract_located_points(load_result)
    if not located_points:
        return {kper: np.zeros((nrow, ncol), dtype=float) for kper in range(nper)}

    x_centers, y_centers = cell_centers_from_sgrid(sgrid, nrow, ncol)
    period_bounds = stress_period_bounds(nper, simulation_window)

    return discretize_located_points(
        located_points=located_points,
        x_centers=x_centers,
        y_centers=y_centers,
        nrow=nrow,
        ncol=ncol,
        nper=nper,
        period_bounds=period_bounds,
        method=method,
        source_unit=source_unit,
    )


def spatial_mean_from_fields(
    load_result: Any,
    *,
    simulation_window: ResolvedSimulationTimeWindow | None = None,
) -> pd.Series | None:
    """Compute the spatial mean of FieldRecords to produce a homogeneous series.

    Reduces gridded data (TIF, NC, xarray) to a single scalar per time step
    by averaging all spatial cells. Returns a pandas Series in mm/day
    (data-manager internal unit) or None if no fields are available.
    """
    del simulation_window  # accepted for API symmetry; not used today.
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
