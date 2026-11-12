"""Cell lookup on the mesh a solver wrote, by row and column or by cell id.

A regular grid names a column by row and column. Any other mesh names it by
row 0 and the cell id. A column with no active cell answers layer 0.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.solver.base.cell_lookup import top_active_layer_on_solver_mesh
from tests._helpers.solver_meshes import solver_mesh_from


def two_quads_in_two_layers() -> SimpleNamespace:
    """Two unit squares side by side. Cell 0 is dry in layer 0, cell 1 is dry in both layers."""
    vertices = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [2, 0], [2, 1]], dtype=float)
    connectivity = np.array([[0, 1, 2, 3], [1, 4, 5, 2]])
    mesh = HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.QUADRILATERAL, connectivity),),
        structured_shape=None,
    )
    solver_mesh = solver_mesh_from(
        mesh,
        top=np.full(2, 10.0),
        botm=np.array([[5.0, 5.0], [0.0, 0.0]]),
        inactive_mask=np.array([[True, True], [False, True]]),
    )
    return SimpleNamespace(solver_model=SimpleNamespace(solver_mesh=solver_mesh))


TOP_LAYERS = [
    # Cell 0 is dry in layer 0 so its top active layer is 1. Cell 1 has none and answers 0.
    pytest.param(0, 1, id="active in the second layer only"),
    pytest.param(1, 0, id="column with no active cell"),
]

REFUSED = [
    pytest.param(1, 0, id="row other than 0"),
    pytest.param(0, 2, id="id past the last cell"),
    pytest.param(0, -1, id="negative id"),
]


@pytest.mark.parametrize(("col", "layer"), TOP_LAYERS)
def test_top_layer_by_cell_id(col: int, layer: int) -> None:
    assert top_active_layer_on_solver_mesh(two_quads_in_two_layers(), 0, col) == layer


def test_no_solver_mesh_gives_none() -> None:
    run = SimpleNamespace(solver_model=None)

    assert top_active_layer_on_solver_mesh(run, 0, 0) is None


@pytest.mark.parametrize(("row", "col"), REFUSED)
def test_refusals(row: int, col: int) -> None:
    with pytest.raises(ValueError, match="addresses a cell as row 0 and col its id, below 2"):
        top_active_layer_on_solver_mesh(two_quads_in_two_layers(), row, col)
