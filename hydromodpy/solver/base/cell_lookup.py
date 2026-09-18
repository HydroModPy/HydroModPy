"""Locate a cell by coordinates on a solver mesh.

Shared by the backends whose model carries a ``solver_mesh``. It lives here, and
not in the layer that asks, because the answer depends on the grid a backend
wrote: the cell order of a Voronoi grid is the one the solver was given, and the
seed triangulation held elsewhere is not it.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.simulation.planning.plan import RunContext


def locate_cell_on_solver_mesh(ctx: RunContext, x: float, y: float) -> tuple[int, int, int] | None:
    """Return the nearest cell selector on ``ctx``'s solver mesh, or ``None``.

    ``(0, row, col)`` on a structured mesh, ``(0, 0, cell_id)`` on an
    unstructured one, which is the flat selector a DISV head extractor reads.
    """
    model = ctx.model
    mesh = getattr(model, "solver_mesh", None)
    if mesh is None:
        return None
    centroids = np.asarray(mesh.cell_centroids(), dtype=float)
    if centroids.ndim != 2 or centroids.shape[0] == 0 or centroids.shape[1] < 2:
        return None
    deltas = centroids[:, :2] - np.array([x, y], dtype=float)
    index = int(np.argmin(np.einsum("ij,ij->i", deltas, deltas)))
    if not mesh.is_structured:
        return (0, 0, index)
    ncol = int(mesh.ncol)
    return (0, index // ncol, index % ncol)


__all__ = ["locate_cell_on_solver_mesh"]
