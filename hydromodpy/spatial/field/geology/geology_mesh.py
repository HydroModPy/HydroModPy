"""A regular planar cell mesh over a bounding box, for the geology demos."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from hydromodpy.spatial.field.core.mesh_cells import cell_mesh_from_edges
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = ("regular_cell_mesh_over_bounds",)


def regular_cell_mesh_over_bounds(
    bounds: Sequence[float], *, crs_wkt: str, target_n_cells: int = 400
) -> PlanarCellMesh:
    """Return a regular grid over ``[xmin, ymin, xmax, ymax]`` of about ``target_n_cells`` cells.

    The cells keep the aspect ratio of the box, at least one per axis. The grid
    is the one of ``cell_mesh_from_edges``, row 0 south.
    """
    xmin, ymin, xmax, ymax = [float(v) for v in bounds]
    if not (np.isfinite(xmin) and np.isfinite(ymin) and np.isfinite(xmax) and np.isfinite(ymax)):
        raise ValueError("bounds must contain finite values")
    if xmax <= xmin or ymax <= ymin:
        raise ValueError("bounds must satisfy xmax > xmin and ymax > ymin")

    target = max(1, int(target_n_cells))
    ratio = (xmax - xmin) / (ymax - ymin)
    n_x = max(2, int(np.round(np.sqrt(float(target) * ratio))) + 1)
    n_y = max(2, int(np.round(np.sqrt(float(target) / ratio))) + 1)
    return cell_mesh_from_edges(
        np.linspace(xmin, xmax, n_x, dtype=float),
        np.linspace(ymin, ymax, n_y, dtype=float),
        crs_wkt=crs_wkt,
    )
