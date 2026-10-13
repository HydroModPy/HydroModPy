"""Readers of a gridded or located source, shared by the forcing discretizers.

The source is whatever the data managers return: an xarray dataset, a NetCDF or
GeoTIFF file, station series. The target is always a flat list of cell centres,
whatever the mesh engine.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.config_kit.types import InterpolationMethod
from hydromodpy.core.units import factor_to_m_per_s
from hydromodpy.spatial.mesh.cartesian_grid.spatial_interpolation import (
    interpolate_points_to_grid,
    interpolate_stack_to_grid,
    interpolate_to_grid,
)


def unit_to_m_per_s_factor(unit: str) -> float:
    """Return multiplication factor to convert from *unit* to m/s."""
    token = "".join(str(unit).strip().lower().split())
    french_aliases = {
        "mm/jour": "mm/day",
        "cm/jour": "cm/day",
        "m/jour": "m/day",
    }
    resolved_unit = french_aliases.get(token, unit)
    return factor_to_m_per_s(resolved_unit)


def pick_field_variable(ds: object) -> str | None:
    """Return the data variable of a gridded dataset that carries the field.

    A CF dataset stores its coordinate reference as a scalar data variable
    sitting next to the field, and a land-surface export carries several
    fields at once. Taking the first variable blindly picks the grid mapping,
    which has no dimension at all: skip anything a field points at as its
    ``grid_mapping``, skip anything with fewer than two dimensions, and keep
    the first of what is left.
    """
    data_vars = list(getattr(ds, "data_vars", ()) or ())
    if not data_vars:
        return None
    grid_mappings = {
        str(ds[name].attrs.get("grid_mapping"))
        for name in data_vars
        if ds[name].attrs.get("grid_mapping")
    }
    for name in data_vars:
        if str(name) in grid_mappings:
            continue
        if len(ds[name].dims) < 2:
            continue
        return str(name)
    return str(data_vars[0])


def find_xy_dims(da: object) -> tuple[str, str]:
    """Identify X and Y dimension names in a DataArray."""
    dims = [str(d) for d in da.dims]
    x_candidates = ("x", "lon", "longitude", "easting", "X")
    y_candidates = ("y", "lat", "latitude", "northing", "Y")
    x_dim = next((d for d in dims if d in x_candidates), None)
    y_dim = next((d for d in dims if d in y_candidates), None)
    # Fallback: use last two spatial dims.
    spatial_dims = [d for d in dims if d != "time"]
    if x_dim is None and len(spatial_dims) >= 1:
        x_dim = spatial_dims[-1]
    if y_dim is None and len(spatial_dims) >= 2:
        y_dim = spatial_dims[-2]
    if x_dim is None or y_dim is None:
        raise ValueError(f"Cannot identify X/Y dimensions in DataArray with dims={dims}")
    return x_dim, y_dim


# The interpolation module takes a 2-D target. A column of cells is one: it has
# as many rows as cells and one column, whatever the mesh topology.


def _as_column(centers: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return the x and y of ``(n, 2)`` centres as two ``(n, 1)`` columns."""
    xy = np.asarray(centers, dtype=float)
    return xy[:, 0].reshape(-1, 1), xy[:, 1].reshape(-1, 1)


def interpolate_on_cells(
    source_values: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    centers: np.ndarray,
    method: InterpolationMethod,
) -> np.ndarray:
    """Interpolate one source slice onto the cell centres, one value per cell."""
    target_x, target_y = _as_column(centers)
    values = interpolate_to_grid(
        np.asarray(source_values, dtype=float),
        source_x,
        source_y,
        target_x,
        target_y,
        target_x.shape[0],
        1,
        method,
    )
    return values.reshape(-1)


def interpolate_stack_on_cells(
    source_stack: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    centers: np.ndarray,
    method: InterpolationMethod,
) -> np.ndarray:
    """Interpolate a stack of source slices onto the cell centres, ``(n_slices, n_cells)``."""
    target_x, target_y = _as_column(centers)
    values = interpolate_stack_to_grid(
        source_stack,
        source_x,
        source_y,
        target_x,
        target_y,
        target_x.shape[0],
        1,
        method,
    )
    return values.reshape(values.shape[0], -1)


def interpolate_points_on_cells(
    point_x: np.ndarray,
    point_y: np.ndarray,
    point_values: np.ndarray,
    centers: np.ndarray,
    method: InterpolationMethod,
) -> np.ndarray:
    """Interpolate scattered station values onto the cell centres, one value per cell."""
    target_x, target_y = _as_column(centers)
    values = interpolate_points_to_grid(
        point_x=point_x,
        point_y=point_y,
        point_values=point_values,
        target_x=target_x,
        target_y=target_y,
        nrow=target_x.shape[0],
        ncol=1,
        method=method,
    )
    return values.reshape(-1)
