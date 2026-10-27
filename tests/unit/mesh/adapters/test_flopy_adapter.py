"""The flopy DISV arguments of a planar HydroMesh."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.adapters.flopy_adapter import to_flopy_disv_args
from tests._helpers.mesh_cases import regular_mesh


def test_a_counterclockwise_triangle_is_written_clockwise() -> None:
    verts = np.array([[0, 0], [1, 0], [0.5, 1]], dtype=float)
    mesh = HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2]])),),
    )
    result = to_flopy_disv_args(mesh, top=10.0, botm=np.array([[5.0]]))
    assert result["nvert"] == 3
    assert result["ncpl"] == 1
    assert len(result["cell2d"]) == 1
    assert len(result["vertices"]) == 3
    assert result["cell2d"][0][4:] == [0, 2, 1]


def test_a_clockwise_grid_keeps_its_rings_and_its_cell_centres() -> None:
    cell_mesh = regular_mesh(2, 3, dx=10.0)

    result = to_flopy_disv_args(cell_mesh.mesh, top=10.0, botm=np.zeros((1, 6)))

    for row, nodes, centre in zip(
        result["cell2d"], cell_mesh.mesh.flat_connectivity, cell_mesh.centers, strict=True
    ):
        assert row[3] == 4
        assert row[4:] == nodes.tolist()
        assert row[1:3] == pytest.approx(centre.tolist())


def test_the_seeds_of_a_voronoi_mesh_are_its_disv_centres() -> None:
    verts = np.array([[1, 0], [1, 1], [0, 1], [-0.3, 0.5], [0, 0], [2, 0], [2, 1]], dtype=float)
    seeds = np.array([[0.3, 0.5], [1.5, 0.5]])
    mesh = HydroMesh(
        vertices=verts,
        cell_blocks=(
            CellBlock(CellType.POLYGON, (np.array([0, 1, 2, 3, 4]), np.array([0, 5, 6, 1]))),
        ),
        cell_data={"disv_cell_center": seeds},
    )

    result = to_flopy_disv_args(mesh, top=10.0, botm=np.zeros((1, 2)))

    assert [row[1:3] for row in result["cell2d"]] == seeds.tolist()
    assert [row[3] for row in result["cell2d"]] == [5, 4]


def test_a_3d_mesh_has_no_disv() -> None:
    verts = np.array(
        [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=float
    )
    mesh = HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(CellType.WEDGE, np.array([[0, 1, 2, 3, 4, 5]])),),
    )
    with pytest.raises(ValueError, match="2D mesh"):
        to_flopy_disv_args(mesh, top=10.0, botm=np.array([[5.0]]))
