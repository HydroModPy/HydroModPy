"""Cells inside a closed face family line, and cells a polygon overlaps.

A mesh whose faces follow a closed family line (a lake shore on triangles)
splits into regions once the faces of that family are cut: a polygon then owns
the regions it covers, cell for cell, with no sliver of a cell outside it. A
mesh whose faces only approach the line (a regular grid, the Voronoi dual of a
triangulation) has no such regions; the cells a polygon overlaps by a positive
area are the cells it reaches there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import shapely
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from shapely.strtree import STRtree

from hydromodpy.spatial.mesh.ops.vector_cell_mask import cell_polygons

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry

    from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = ["family_regions", "interior_cells", "polygon_overlap"]

_INTERIOR_SHARE = 0.5
"""A region belongs to the polygon that covers more than this share of its area."""

_MIN_OVERLAP_SHARE = 1e-6
"""An overlap below this share of the cell area is a sliver, not a reach."""


def polygon_overlap(
    cell_mesh: PlanarCellMesh, polygon: BaseGeometry
) -> tuple[np.ndarray, np.ndarray]:
    """Return the sorted ids of the cells ``polygon`` overlaps, and the overlap areas.

    A cell that only touches the polygon along an edge or at a point has no
    positive overlap and is left out. A sliver smaller than
    ``_MIN_OVERLAP_SHARE`` of the cell area is left out too: it is a rounding
    artefact of the outline, not a reach.
    """
    polygons = cell_polygons(cell_mesh.mesh.vertices, cell_mesh.geometry.padded_connectivity)
    candidates = np.sort(STRtree(polygons).query(polygon, predicate="intersects"))
    areas = shapely.area(shapely.intersection(polygons[candidates], polygon))
    cell_areas = np.asarray(cell_mesh.geometry.areas, dtype=float)[candidates]
    keep = areas > _MIN_OVERLAP_SHARE * cell_areas
    return candidates[keep].astype(np.int64), np.asarray(areas[keep], dtype=float)


def family_regions(cell_mesh: PlanarCellMesh, family: str) -> np.ndarray:
    """Return the region label of every cell once the faces of ``family`` are cut."""
    geometry = cell_mesh.geometry
    n_cells = cell_mesh.n_cells
    n_nodes = np.int64(cell_mesh.mesh.n_nodes)
    edge_keys = geometry.edge_nodes[:, 0] * n_nodes + geometry.edge_nodes[:, 1]
    cut = np.zeros(edge_keys.size, dtype=bool)
    rows = cell_mesh.face_rows(family)
    if rows.any():
        table = cell_mesh.face_families
        node_a, node_b = table.node_a[rows], table.node_b[rows]
        family_keys = np.minimum(node_a, node_b) * n_nodes + np.maximum(node_a, node_b)
        cut = np.isin(edge_keys, family_keys)
    joined = (geometry.edge_cells[:, 1] >= 0) & ~cut
    first, second = geometry.edge_cells[joined, 0], geometry.edge_cells[joined, 1]
    graph = coo_matrix(
        (np.ones(first.size, dtype=np.int8), (first, second)), shape=(n_cells, n_cells)
    )
    _, labels = connected_components(graph, directed=False)
    return labels.astype(np.int64)


def interior_cells(cell_mesh: PlanarCellMesh, family: str, polygon: BaseGeometry) -> np.ndarray:
    """Return the sorted cells of the ``family`` regions ``polygon`` covers for most of their area.

    Each region bounded by the faces of ``family`` is owned by the polygon that
    covers more than half of it, so a cell is inside or outside as a whole. An
    empty result means no region of the family lies inside the polygon: the
    mesh faces were not built on its outline.
    """
    labels = family_regions(cell_mesh, family)
    n_regions = int(labels.max(initial=-1)) + 1
    cells, overlap = polygon_overlap(cell_mesh, polygon)
    covered = np.bincount(labels[cells], weights=overlap, minlength=n_regions)
    region_area = np.bincount(labels, weights=cell_mesh.geometry.areas, minlength=n_regions)
    inside = covered > _INTERIOR_SHARE * region_area
    return np.flatnonzero(inside[labels]).astype(np.int64)
