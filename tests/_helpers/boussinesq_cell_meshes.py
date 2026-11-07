"""A cell mesh for a ``BoussinesqMesh`` whose arrays a test sets by hand.

The solver mesh always holds a cell mesh. A test that builds its arrays by hand and
never reads sides, river or cell location from the cell mesh only needs one of the
right size. Not public API.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
from tests._helpers.cell_meshes import cell_mesh_of


def placeholder_cell_mesh(n_cells: int) -> PlanarCellMesh:
    """Return a zigzag strip of ``n_cells`` triangles, with no face family."""
    n_nodes = n_cells + 2
    vertices = np.column_stack([np.arange(n_nodes) // 2, np.arange(n_nodes) % 2]).astype(float)
    triangles = np.column_stack(
        [np.arange(n_cells), np.arange(n_cells) + 1, np.arange(n_cells) + 2]
    )
    return cell_mesh_of(
        HydroMesh(vertices=vertices, cell_blocks=(CellBlock(CellType.TRIANGLE, triangles),))
    )
