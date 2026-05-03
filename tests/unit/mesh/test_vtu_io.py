"""Tests for VTU read/write."""

import numpy as np
import pytest

from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh


@pytest.fixture
def triangle_mesh() -> HydroMesh:
    verts = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 1]], dtype=float)
    conn = np.array([[0, 1, 2], [1, 3, 2]], dtype=int)
    return HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(CellType.TRIANGLE, conn),),
        cell_data={"conductivity": np.array([1e-4, 2e-4])},
    )


def test_vtu_roundtrip(tmp_path, triangle_mesh) -> None:
    import meshio  # noqa: F401

    from hydromodpy.spatial.mesh.io import read_vtu, write_vtu

    path = write_vtu(tmp_path / "test.vtu", triangle_mesh)
    assert path.exists()

    recovered = read_vtu(path)
    assert recovered.n_cells == 2
    assert recovered.n_nodes == 4
    np.testing.assert_array_almost_equal(recovered.cell_data["conductivity"], [1e-4, 2e-4])
