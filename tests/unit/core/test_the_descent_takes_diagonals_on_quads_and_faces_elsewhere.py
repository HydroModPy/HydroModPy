"""D descends by shared nodes on a quad grid and by shared faces elsewhere.

On quads a diagonal neighbour is taken when its drop per metre is the steepest,
the D8 rule the stream criterion uses. A triangle shares nodes with about a
dozen others and no direction there is a diagonal, so the graph falls back to
shared faces, and the fill and the receivers both use that one graph.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.descent import build_descent
from hydromodpy.core.field_routing import cell_adjacency_from_face_connectivity
from tests.unit.core._descent_meshes import grid_descent, triangle_mesh

N = 5
CENTRE = 2 * N + 2
DIAGONAL = 1 * N + 1


def _centre_with_a_steep_diagonal() -> np.ndarray:
    top = np.full((N, N), 9.5)
    top[0, :] = top[-1, :] = top[:, 0] = top[:, -1] = 1.0
    top[2, 2] = 10.0
    top[1, 2] = top[3, 2] = top[2, 1] = top[2, 3] = 9.0
    # A drop of 3 over sqrt(2) beats a drop of 1 over 1.
    top[1, 1] = 7.0
    return top


def test_the_steepest_diagonal_is_the_receiver_on_quads() -> None:
    descent = grid_descent(_centre_with_a_steep_diagonal())

    assert descent.diagonal_neighbors
    assert int(descent.receiver[CENTRE]) == DIAGONAL


def test_without_diagonals_the_receiver_shares_a_face() -> None:
    descent = grid_descent(_centre_with_a_steep_diagonal(), diagonal_neighbors=False)

    assert not descent.diagonal_neighbors
    assert int(descent.receiver[CENTRE]) in {1 * N + 2, 3 * N + 2, 2 * N + 1, 2 * N + 3}


def test_a_triangle_mesh_descends_by_shared_faces() -> None:
    vertices, connectivity, centroids = triangle_mesh(4, 4)
    n_cells = connectivity.shape[0]

    descent = build_descent(
        centroids[:, 0] + centroids[:, 1],
        connectivity,
        vertices=vertices,
        centroids=centroids,
        routable=np.ones(n_cells, dtype=bool),
        diagonal_neighbors=True,
    )

    assert not descent.diagonal_neighbors
    assert descent.adjacency == cell_adjacency_from_face_connectivity(connectivity, n_cells=n_cells)
    for cell in np.flatnonzero(descent.receiver >= 0).tolist():
        assert int(descent.receiver[cell]) in descent.adjacency[cell]
