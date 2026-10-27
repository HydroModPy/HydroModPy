"""The angle between the link of two cell centres and the normal of the face they share."""

from __future__ import annotations

import numpy as np

from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.ops.mesh_orthogonality import (
    connection_nonorthogonality_deg,
    nonorthogonality_summary,
)
from tests._helpers.mesh_cases import regular_mesh

PENTAGON_AND_QUAD = np.array(
    [[1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [-0.3, 0.5], [0.0, 0.0], [2.0, 0.0], [2.0, 1.0]]
)
"""A left pentagon and a right quad that share the vertical edge (1, 0)-(1, 1)."""


def _ragged(centres: list[list[float]]) -> HydroMesh:
    cells = (np.array([0, 1, 2, 3, 4]), np.array([0, 5, 6, 1]))
    return HydroMesh(
        vertices=PENTAGON_AND_QUAD,
        cell_blocks=(CellBlock(cell_type=CellType.POLYGON, connectivity=cells),),
        cell_data={"disv_cell_center": np.array(centres, dtype=float)},
    )


def test_a_ragged_mesh_is_measured_from_its_seed_centres() -> None:
    # The seeds (0.3, 0.5) and (1.5, 0.5) lie on a horizontal line across the
    # vertical shared face: the connection is perpendicular to it.
    angles = connection_nonorthogonality_deg(_ragged([[0.3, 0.5], [1.5, 0.5]]))

    assert angles.shape == (1,)
    assert angles[0] < 1e-6


def test_a_link_tilted_by_45_degrees_is_45_degrees_off() -> None:
    angles = connection_nonorthogonality_deg(_ragged([[0.5, 0.0], [1.5, 1.0]]))

    np.testing.assert_allclose(angles, [45.0])


def test_a_grid_is_orthogonal_on_every_interior_face() -> None:
    summary = nonorthogonality_summary(regular_mesh(3, 4, dx=25.0).mesh)

    assert summary["n"] == 3 * 3 + 2 * 4
    assert summary["max"] == 0.0
    assert summary["frac_gt_30"] == 0.0


def test_a_face_of_zero_length_and_cells_on_one_centre_are_not_measured() -> None:
    # Nodes 1 and 2 sit on one point: the face between the two triangles has no length.
    vertices = np.array([[0.0, 0.0], [1.0, 1.0], [1.0, 1.0], [2.0, 0.0]])
    collapsed = HydroMesh(
        vertices=vertices, cell_blocks=(CellBlock(CellType.TRIANGLE, [[0, 1, 2], [2, 1, 3]]),)
    )
    same_centre = _ragged([[1.0, 0.5], [1.0, 0.5]])

    assert connection_nonorthogonality_deg(collapsed).size == 0
    assert connection_nonorthogonality_deg(same_centre).size == 0


def test_a_mesh_without_a_cell_has_a_summary_of_zeros() -> None:
    empty = HydroMesh(
        vertices=PENTAGON_AND_QUAD,
        cell_blocks=(CellBlock(cell_type=CellType.POLYGON, connectivity=()),),
    )

    assert connection_nonorthogonality_deg(empty).size == 0
    assert set(nonorthogonality_summary(empty).values()) == {0.0}
