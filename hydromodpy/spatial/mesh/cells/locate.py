"""Locate the cell that holds each point of a planar cell mesh.

One vectorised answer for every consumer: wells, observation points and gauges.
A regular grid is read by floor arithmetic on its bounds, any other mesh by
point-in-polygon on the cell polygons. :func:`locate_cells_near` also takes a
point just outside the mesh, within one cell size of the nearest cell.
"""

from __future__ import annotations

import numpy as np
import shapely
from scipy.spatial import cKDTree
from shapely.strtree import STRtree

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.mesh.model.geometry import cell_polygons
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = ["locate_cells", "locate_cells_near"]

logger = get_logger(__name__)

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


def locate_cells_near(cell_mesh: PlanarCellMesh, xy: np.ndarray) -> np.ndarray:
    """Return the cell of each point, or of the nearest centre within one cell size.

    A point inside the mesh gets the cell that holds it, as :func:`locate_cells`
    gives it. A point outside takes the cell whose centre is the nearest, but only
    when its distance to that cell is at most the cell size, the square root of
    the cell area. Farther out it gets ``-1`` and a warning names the point: a
    gauge or a piezometer that far from the mesh is a coordinate error, and the
    nearest cell would score it on a place it does not observe.
    """
    points = np.atleast_2d(np.asarray(xy, dtype=float))
    cells = locate_cells(cell_mesh, points, allow_nearest=False)
    lost = np.flatnonzero(cells == _OUTSIDE)
    if lost.size == 0:
        return cells
    _, nearest = cKDTree(cell_mesh.centers).query(points[lost])
    nearest = np.asarray(nearest, dtype=np.int64)
    rows = cell_mesh.geometry.padded_connectivity[nearest]
    polygons = cell_polygons(cell_mesh.mesh.vertices, rows)
    distance = shapely.distance(polygons, shapely.points(points[lost]))
    size = np.sqrt(np.asarray(cell_mesh.geometry.areas, dtype=float)[nearest])
    near = distance <= size
    cells[lost[near]] = nearest[near]
    for index in np.flatnonzero(~near).tolist():
        x, y = points[lost[index]]
        logger.warning(
            "Point (%.2f, %.2f) lies %.1f m outside the mesh, farther than the size "
            "%.1f m of the nearest cell %d; it is not located on any cell.",
            x,
            y,
            float(distance[index]),
            float(size[index]),
            int(nearest[index]),
        )
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
