"""Regions of the cells of a mesh once the faces of a family are cut.

``components_without`` cuts by cell pair and ``family_regions`` by edge. The
labels number the regions in the order of their first cell.
"""

from __future__ import annotations

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components

from hydromodpy.spatial.mesh.model.geometry import DerivedGeometry
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh

__all__ = ["components_without", "family_regions"]


def components_without(
    geometry: DerivedGeometry, cut_a: np.ndarray, cut_b: np.ndarray
) -> np.ndarray:
    """Connected components of the cells once the faces ``cut_a | cut_b`` are cut.

    The cut goes by cell pair: two cells that share several edges are split
    when their pair is cut, whatever edge the pair came from.
    """
    return _components_across(geometry, _pair_edges(geometry, cut_a, cut_b))


def family_regions(cell_mesh: PlanarCellMesh, family: str) -> np.ndarray:
    """Return the region label of every cell once the faces of ``family`` are cut.

    The cut goes by edge: two cells that share an edge outside the family stay
    in one region.
    """
    geometry = cell_mesh.geometry
    cut = np.zeros(geometry.edge_nodes.shape[0], dtype=bool)
    rows = cell_mesh.face_rows(family)
    if rows.any():
        table = cell_mesh.face_families
        edges = geometry.edge_ids(table.node_a[rows], table.node_b[rows])
        cut[edges[edges >= 0]] = True
    return _components_across(geometry, cut).astype(np.int64)


def _pair_edges(geometry: DerivedGeometry, cell_a: np.ndarray, cell_b: np.ndarray) -> np.ndarray:
    """Mask of the interior edges whose two cells are one of the pairs ``cell_a | cell_b``."""
    n_cells = geometry.n_cells
    interior = geometry.edge_cells[:, 1] >= 0
    pairs = geometry.edge_cells[interior]
    inside = cell_b >= 0
    keys = np.minimum(cell_a, cell_b)[inside] * n_cells + np.maximum(cell_a, cell_b)[inside]
    cut = np.zeros(geometry.edge_cells.shape[0], dtype=bool)
    cut[interior] = np.isin(pairs[:, 0] * n_cells + pairs[:, 1], keys)
    return cut


def _components_across(geometry: DerivedGeometry, cut: np.ndarray) -> np.ndarray:
    """Connected components of the cells through the interior edges left uncut."""
    n_cells = geometry.n_cells
    joined = (geometry.edge_cells[:, 1] >= 0) & ~cut
    first, second = geometry.edge_cells[joined, 0], geometry.edge_cells[joined, 1]
    graph = coo_matrix(
        (np.ones(first.size, dtype=np.int8), (first, second)), shape=(n_cells, n_cells)
    )
    return connected_components(graph, directed=False)[1]
