"""RCHA and EVTA name the top active layer only when a pass-through cell needs it.

MODFLOW 6 moves the flux of an inactive top cell down by itself and drops the
flux of a pass-through cell. A stack without pass-through cell writes no layer
array, so its files do not change.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.solver.modflow6.builders import areal_layer_index
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays


def _mesh(idomain: np.ndarray) -> SolverMesh:
    top = np.full(4, 100.0)
    botm = np.vstack([np.full(4, 90.0), np.full(4, 80.0), np.full(4, 70.0)])
    mesh = solver_mesh_from_structured_arrays(nrow=2, ncol=2, top=top, botm=botm)
    return SolverMesh(cell_mesh=mesh.cell_mesh, top=mesh.top, botm=mesh.botm, idomain=idomain)


def test_a_stack_without_pass_through_cell_writes_no_layer_array() -> None:
    idomain = np.ones((3, 4), dtype=int)
    idomain[0, 1] = 0

    assert areal_layer_index(_mesh(idomain)) is None


def test_a_pass_through_cell_sends_the_flux_to_the_top_active_layer() -> None:
    idomain = np.ones((3, 4), dtype=int)
    idomain[0, 1] = -1
    idomain[:2, 2] = [0, -1]
    idomain[:, 3] = 0

    np.testing.assert_array_equal(areal_layer_index(_mesh(idomain)), [0, 1, 2, 0])
