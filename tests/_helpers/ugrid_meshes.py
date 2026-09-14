"""Synthetic UGRID meshes for the routing and downslope-distance unit suites.

The builders return the two arrays every ``core.field_routing`` entry point
reads: ``vertices`` as ``(n_nodes, 3)`` and a dense ``face_node_connectivity``
as ``(n_cells, 4)``. Cells are numbered row-major, so a structured field can be
reshaped to ``(nrow, ncol)`` without any index bookkeeping.
"""

from __future__ import annotations

import numpy as np


def quad_mesh(nrow: int, ncol: int, *, cell_size: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """Return (vertices, face_node_connectivity) for a structured quad mesh.

    Cell ``(row, col)`` has id ``row * ncol + col`` and its centroid sits at
    ``((col + 0.5) * cell_size, (row + 0.5) * cell_size)``.
    """
    nodes_per_row = ncol + 1
    rows = np.arange(nrow, dtype=int)[:, None]
    cols = np.arange(ncol, dtype=int)[None, :]
    corner = (rows * nodes_per_row + cols).reshape(-1)
    connectivity = np.column_stack(
        [corner, corner + 1, corner + nodes_per_row + 1, corner + nodes_per_row]
    )
    xx, yy = np.meshgrid(
        np.arange(ncol + 1, dtype="float64") * float(cell_size),
        np.arange(nrow + 1, dtype="float64") * float(cell_size),
    )
    vertices = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(xx.size)])
    return vertices, connectivity


def king_adjacency(nrow: int, ncol: int) -> list[set[int]]:
    """Eight-neighbor adjacency on a structured grid, diagonals included.

    This is the shared-node neighborhood of :func:`quad_mesh`, which the D8
    convention of the paper needs and shared-edge adjacency cannot express.
    """
    adjacency: list[set[int]] = [set() for _ in range(nrow * ncol)]
    for row in range(nrow):
        for col in range(ncol):
            for row_shift in (-1, 0, 1):
                for col_shift in (-1, 0, 1):
                    if row_shift == 0 and col_shift == 0:
                        continue
                    near_row = row + row_shift
                    near_col = col + col_shift
                    if 0 <= near_row < nrow and 0 <= near_col < ncol:
                        adjacency[row * ncol + col].add(near_row * ncol + near_col)
    return adjacency
