"""Grid utilities for field discretization on structured grids."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from hydromodpy.core.units import factor_to_m_per_s

if TYPE_CHECKING:
    from hydromodpy.core.time import ResolvedSimulationTimeWindow


def cell_centers_from_sgrid(
    sgrid: object,
    nrow: int,
    ncol: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract 2-D arrays of cell-center X and Y coordinates.

    Returns (x_centers, y_centers) each shaped ``(nrow, ncol)``.
    """
    # Prefer explicit cell-center arrays (guarded: FloPy properties may
    # raise when top/botm are not set).
    try:
        xc = getattr(sgrid, "xcellcenters", None)
        yc = getattr(sgrid, "ycellcenters", None)
        if xc is not None and yc is not None:
            xc = np.asarray(xc, dtype=float)
            yc = np.asarray(yc, dtype=float)
            if xc.ndim == 2 and yc.ndim == 2:
                return xc, yc
    except Exception:
        pass

    # Fallback: compute from delr/delc + offsets.
    delr = np.asarray(sgrid.delr, dtype=float).reshape(-1)
    delc = np.asarray(sgrid.delc, dtype=float).reshape(-1)
    xoff = float(getattr(sgrid, "xoffset", getattr(sgrid, "xoff", 0.0)))
    yoff = float(getattr(sgrid, "yoffset", getattr(sgrid, "yoff", 0.0)))

    x_edges = xoff + np.concatenate(([0.0], np.cumsum(delr)))
    y_edges = yoff + np.concatenate(([0.0], np.cumsum(delc)))
    x_cell = 0.5 * (x_edges[:-1] + x_edges[1:])
    y_cell = 0.5 * (y_edges[:-1] + y_edges[1:])

    x_centers, y_centers = np.meshgrid(x_cell, y_cell, indexing="xy")
    return x_centers, y_centers


def stress_period_bounds(
    nper: int,
    simulation_window: ResolvedSimulationTimeWindow | None,
) -> list[tuple[pd.Timestamp, pd.Timestamp]] | None:
    """Return (start, end) bounds for each stress period, or None."""
    if simulation_window is None:
        return None

    from hydromodpy.core.time import build_simulation_time_boundaries

    boundaries = build_simulation_time_boundaries(simulation_window)
    if len(boundaries) < 2:
        return None

    bounds = []
    for i in range(min(nper, len(boundaries) - 1)):
        bounds.append((boundaries[i], boundaries[i + 1]))
    return bounds


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


def interp_2d(
    source_values: np.ndarray,
    source_x: np.ndarray,
    source_y: np.ndarray,
    target_x: np.ndarray,
    target_y: np.ndarray,
    nrow: int,
    ncol: int,
    method: str = "nearest",
) -> np.ndarray:
    """Interpolate a 2-D source array onto target cell centers.

    Delegates to the shared :mod:`spatial_interpolation` module.
    """
    from hydromodpy.spatial.mesh.cartesian_grid.spatial_interpolation import (
        interpolate_to_grid,
    )

    return interpolate_to_grid(
        source_values=np.asarray(source_values, dtype=float),
        source_x=source_x,
        source_y=source_y,
        target_x=target_x,
        target_y=target_y,
        nrow=nrow,
        ncol=ncol,
        method=method,
    )
