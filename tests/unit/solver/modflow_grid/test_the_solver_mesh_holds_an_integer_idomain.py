"""The solver mesh holds MODFLOW's ``idomain`` and answers the top active cell from it."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays

TOP = np.array([10.0, 11.0, 12.0])
BOTM = np.array([[6.0, 7.0, 8.0], [0.0, 1.0, 2.0]])


def _mesh(idomain: np.ndarray) -> SolverMesh:
    base = solver_mesh_from_structured_arrays(nrow=1, ncol=3, top=TOP, botm=BOTM)
    return SolverMesh(cell_mesh=base.cell_mesh, top=base.top, botm=base.botm, idomain=idomain)


def test_the_idomain_keeps_its_three_values_and_cannot_be_written() -> None:
    mesh = _mesh(np.array([[1, 0, 1], [1, 1, -1]]))
    assert mesh.idomain.tolist() == [[1, 0, 1], [1, 1, -1]]
    with pytest.raises(ValueError):
        mesh.idomain[0, 0] = 0


def test_a_value_other_than_minus_one_zero_and_one_is_refused() -> None:
    with pytest.raises(ValueError, match="only -1, 0 and 1"):
        _mesh(np.array([[1, 2, 1], [1, 1, 1]]))


def test_a_pass_through_cell_is_not_active() -> None:
    mesh = _mesh(np.array([[1, 0, 1], [1, 1, -1]]))
    assert mesh.inactive_mask.tolist() == [[False, True, False], [False, False, True]]


def test_the_top_active_cell_and_its_top_follow_the_idomain() -> None:
    mesh = _mesh(np.array([[1, 0, 0], [1, 1, 0]]))
    assert mesh.top_active_layer().tolist() == [0, 1, -1]
    tops = mesh.top_active_cell_top()
    assert tops[:2].tolist() == [10.0, 7.0]
    assert np.isnan(tops[2])


def test_a_closed_column_has_no_active_cell_or_is_covered() -> None:
    mesh = _mesh(np.array([[1, 0, 0], [1, 1, 0]]))
    assert mesh.closed_surface().tolist() == [False, False, True]
    assert mesh.closed_surface([1]).tolist() == [False, True, True]


def test_the_interfaces_are_checked_on_demand() -> None:
    mesh = _mesh(np.ones((2, 3), dtype=int))
    mesh.check_interfaces()
    flat = SolverMesh(
        cell_mesh=mesh.cell_mesh, top=mesh.top, botm=np.vstack([TOP, BOTM[1]]), idomain=mesh.idomain
    )
    with pytest.raises(ValueError, match="layer 0 cell 0"):
        flat.check_interfaces()
