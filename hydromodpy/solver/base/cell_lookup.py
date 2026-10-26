"""Locate a cell by coordinates on a solver mesh.

Shared by the backends whose model carries a cell mesh. It lives here, and not
in the layer that asks, because the answer depends on the grid a backend wrote:
the cell order of a Voronoi grid is the one the solver was given, and the seed
triangulation held elsewhere is not it.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.simulation.planning.plan import RunContext
from hydromodpy.spatial.mesh.model.planar_cell_mesh import PlanarCellMesh
from hydromodpy.spatial.mesh.ops.cell_location import locate_cells_near


def locate_cell_on_cell_mesh(
    cell_mesh: PlanarCellMesh, x: float, y: float
) -> tuple[int, int, int] | None:
    """Return the flat selector ``(0, 0, cell_id)`` of the cell that holds ``(x, y)``.

    A point outside every cell takes the cell whose centre is the nearest, when it
    lies within one cell size of that cell. Farther out the answer is ``None`` and
    a warning names the point.
    """
    cell_id = int(locate_cells_near(cell_mesh, np.array([[x, y]], dtype=float))[0])
    return None if cell_id < 0 else (0, 0, cell_id)


def locate_cell_on_solver_mesh(ctx: RunContext, x: float, y: float) -> tuple[int, int, int] | None:
    """Return the cell selector that holds ``(x, y)`` on ``ctx``'s solver mesh, or ``None``.

    The selector is ``(0, 0, cell_id)`` on every mesh, which is the flat selector
    a DISV head extractor reads. ``None`` without a solver mesh, or for a point
    farther than one cell size from the mesh (see :func:`locate_cell_on_cell_mesh`).
    """
    mesh = getattr(ctx.model, "solver_mesh", None)
    if mesh is None:
        return None
    return locate_cell_on_cell_mesh(mesh.cell_mesh, x, y)


__all__ = ["locate_cell_on_cell_mesh", "locate_cell_on_solver_mesh"]
