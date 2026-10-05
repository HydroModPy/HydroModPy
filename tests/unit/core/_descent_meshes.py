"""Small meshes the descent D is built on in the unit tests.

``grid_descent`` builds D on a structured quad grid of unit cells, cell
``(row, col)`` numbered ``row * ncol + col``. ``triangle_mesh`` splits each
unit square in two, a mesh with no diagonal, padded with -1 to four nodes.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.core.descent import Descent, build_descent
from hydromodpy.core.field_routing import cell_centroids_from_mesh
from tests._helpers.ugrid_meshes import quad_mesh


def grid_centres(nrow: int, ncol: int) -> np.ndarray:
    """Return the centre of each unit cell, row-major."""
    rows, cols = np.divmod(np.arange(nrow * ncol), ncol)
    return np.column_stack([cols + 0.5, rows + 0.5]).astype(float)


def grid_descent(top: np.ndarray, **options: object) -> Descent:
    """Build D on the quad grid ``top`` describes, every cell routable by default."""
    nrow, ncol = np.shape(top)
    vertices, connectivity = quad_mesh(nrow, ncol)
    options.setdefault("routable", np.ones(nrow * ncol, dtype=bool))
    return build_descent(
        np.asarray(top, dtype=float).reshape(-1),
        connectivity,
        vertices=vertices,
        centroids=grid_centres(nrow, ncol),
        **options,
    )


def triangle_mesh(nrow: int, ncol: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (vertices, padded connectivity, centroids) of a triangulated grid."""
    vertices, quads = quad_mesh(nrow, ncol)
    triangles = []
    for a, b, c, d in quads.tolist():
        triangles.append([a, b, c, -1])
        triangles.append([a, c, d, -1])
    connectivity = np.asarray(triangles, dtype=int)
    return vertices, connectivity, cell_centroids_from_mesh(vertices, connectivity)


def chain_ends_without_cycle(descent: Descent) -> bool:
    """Return whether every receiver chain stops within the cell count."""
    receiver = descent.receiver
    for start in np.flatnonzero(descent.routable).tolist():
        cell, steps = start, 0
        while receiver[cell] >= 0:
            cell = int(receiver[cell])
            steps += 1
            if steps > receiver.size:
                return False
    return True
