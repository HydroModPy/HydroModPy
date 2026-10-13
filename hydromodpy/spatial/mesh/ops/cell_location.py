"""Locate the cell that holds each point of a planar cell mesh.

One vectorised answer for every consumer: wells, observation points and gauges.
A regular grid is read by floor arithmetic on its bounds, any other mesh by
point-in-polygon on the cell polygons.
"""

from __future__ import annotations

import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.strtree import STRtree

from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_polygons

__all__ = ["locate_cells"]

_OUTSIDE = -1


def locate_cells(cell_mesh: PlanarCellMesh, xy: np.ndarray, *, allow_nearest: bool) -> np.ndarray:
    """Return, for each point of ``xy`` ``(n, 2)``, the id of the cell that holds it.

    A point on a shared edge or vertex belongs to the cell of smallest id on an
    unstructured mesh; on a regular grid it belongs to the cell east or south of
    it, and a point on the east or south border of the grid to the last column
    or row. A point outside every cell gets ``-1``, or, when ``allow_nearest``
    is true, the cell whose centre is the nearest.
    """
    points = np.atleast_2d(np.asarray(xy, dtype=float))
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError(f"xy must have shape (n, 2), got {points.shape}")
    if cell_mesh.structured_shape is not None:
        cells = _locate_on_grid(cell_mesh, points)
    else:
        cells = _locate_in_polygons(cell_mesh, points)
    if allow_nearest:
        lost = cells == _OUTSIDE
        if lost.any():
            _, nearest = cKDTree(cell_mesh.centers).query(points[lost])
            cells[lost] = nearest
    return cells


def _locate_on_grid(cell_mesh: PlanarCellMesh, points: np.ndarray) -> np.ndarray:
    """Floor arithmetic on the bounds of a regular grid, row 0 north."""
    nrow, ncol = cell_mesh.structured_shape
    xmin, ymin, xmax, ymax = (float(v) for v in cell_mesh.mesh.bounds())
    dx = (xmax - xmin) / ncol
    dy = (ymax - ymin) / nrow
    x, y = points[:, 0], points[:, 1]
    inside = (x >= xmin) & (x <= xmax) & (y >= ymin) & (y <= ymax)
    with np.errstate(invalid="ignore"):
        col = np.minimum(np.trunc((x - xmin) / dx), ncol - 1)
        row = np.minimum(np.trunc((ymax - y) / dy), nrow - 1)
    cells = np.full(points.shape[0], _OUTSIDE, dtype=np.int64)
    cells[inside] = row[inside].astype(np.int64) * ncol + col[inside].astype(np.int64)
    return cells


def _locate_in_polygons(cell_mesh: PlanarCellMesh, points: np.ndarray) -> np.ndarray:
    """Smallest id among the cell polygons that cover each point."""
    polygons = cell_polygons(cell_mesh.mesh.vertices, cell_mesh.geometry.padded_connectivity)
    point_index, cell_index = STRtree(polygons).query(
        shapely.points(points), predicate="covered_by"
    )
    cells = np.full(points.shape[0], np.iinfo(np.int64).max, dtype=np.int64)
    np.minimum.at(cells, point_index, cell_index)
    cells[cells == np.iinfo(np.int64).max] = _OUTSIDE
    return cells
