"""Locate a cell by coordinates on a solver mesh.

Shared by the backends whose model carries a ``solver_mesh``. It lives here, and
not in the layer that asks, because the answer depends on the grid a backend
wrote: the cell order of a Voronoi grid is the one the solver was given, and the
seed triangulation held elsewhere is not it.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.simulation.planning.plan import RunContext
from hydromodpy.spatial.mesh.ops.cell_location import locate_cells


def locate_cell_on_solver_mesh(ctx: RunContext, x: float, y: float) -> tuple[int, int, int] | None:
    """Return the cell selector that holds ``(x, y)`` on ``ctx``'s solver mesh, or ``None``.

    The selector is ``(0, 0, cell_id)`` on every mesh, which is the flat selector
    a DISV head extractor reads. A point outside every cell takes the cell whose
    centre is the nearest.
    """
    mesh = getattr(ctx.model, "solver_mesh", None)
    if mesh is None:
        return None
    cell_id = locate_cells(mesh.cell_mesh, np.array([[x, y]], dtype=float), allow_nearest=True)[0]
    return (0, 0, int(cell_id))


__all__ = ["locate_cell_on_solver_mesh"]
