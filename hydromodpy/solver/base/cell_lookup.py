"""Locate a cell by coordinates on a solver mesh.

Shared by the backends whose model carries a cell mesh. It lives here, and not
in the layer that asks, because the answer depends on the grid a backend wrote:
the cell order of a Voronoi grid is the one the solver was given, and the seed
triangulation held elsewhere is not it.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.mesh.cells.locate import locate_cells_near
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from hydromodpy.solver.base.plan import RunContext


def locate_cell_on_cell_mesh(
    cell_mesh: PlanarCellMesh, x: float, y: float
) -> tuple[int, int, int] | None:
    """Return the flat selector ``(0, 0, cell_id)`` of the cell that holds ``(x, y)``.

    A point outside every cell takes the cell whose center is the nearest, when it
    lies within one cell size of that cell. Farther out the answer is ``None`` and
    a warning names the point.
    """
    cell_id = int(locate_cells_near(cell_mesh, np.array([[x, y]], dtype=float))[0])
    return None if cell_id < 0 else (0, 0, cell_id)


def locate_cell_on_solver_mesh(ctx: RunContext, x: float, y: float) -> tuple[int, int, int] | None:
    """Return the cell selector that holds ``(x, y)`` on ``ctx``'s solver mesh, or ``None``.

    The selector is ``(layer, 0, cell_id)``, the flat selector a DISV head
    extractor reads. A point has no layer, so it reads the top active cell of
    its column (layer 0 for a column with no active cell). ``None`` without a
    solver mesh, or for a point farther than one cell size from the mesh (see
    :func:`locate_cell_on_cell_mesh`).
    """
    mesh = getattr(ctx.model, "solver_mesh", None)
    if mesh is None:
        return None
    located = locate_cell_on_cell_mesh(mesh.cell_mesh, x, y)
    if located is None:
        return None
    cell_id = located[2]
    return (max(int(mesh.top_active_layer()[cell_id]), 0), 0, cell_id)


def top_active_layer_on_solver_mesh(ctx: RunContext, row: int, col: int) -> int | None:
    """Return the top active layer of the column at ``(row, col)`` on ``ctx``'s solver mesh.

    A regular grid names the column by its row and column, any other mesh by
    row 0 and the cell id in ``col``. A column with no active cell answers 0,
    like :func:`locate_cell_on_solver_mesh`. ``None`` without a solver mesh.

    Raises
    ------
    ValueError
        When ``(row, col)`` names no column of the mesh.
    """
    mesh = getattr(ctx.model, "solver_mesh", None)
    if mesh is None:
        return None
    layers = mesh.top_active_layer()
    if mesh.is_structured:
        nrow, ncol = mesh.structured_shape
        if not (0 <= row < nrow and 0 <= col < ncol):
            raise ValueError(f"row {row}, col {col} is outside the {nrow} x {ncol} grid.")
        return max(int(layers.reshape(nrow, ncol)[row, col]), 0)
    if row != 0 or not 0 <= col < layers.size:
        raise ValueError(
            f"row {row}, col {col} names no cell: an unstructured mesh addresses a cell "
            f"as row 0 and col its id, below {layers.size}."
        )
    return max(int(layers[col]), 0)


__all__ = [
    "locate_cell_on_cell_mesh",
    "locate_cell_on_solver_mesh",
    "top_active_layer_on_solver_mesh",
]
