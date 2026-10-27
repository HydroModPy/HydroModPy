"""A HydroMesh written to a VTU file reads back with its cells and its fields."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.io import read_vtu, write_vtu
from tests._helpers.mesh_cases import L93_ORIGIN, regular_mesh

WEDGE_COLUMN = np.array(
    [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1]], dtype=float
)


def _triangles() -> HydroMesh:
    verts = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 1]], dtype=float)
    return HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2], [1, 3, 2]])),),
        cell_data={"conductivity": np.array([1e-4, 2e-4])},
    )


def _grid_in_lambert93() -> HydroMesh:
    mesh = regular_mesh(3, 4, dx=25.0, xmin=L93_ORIGIN[0], ymin=L93_ORIGIN[1]).mesh
    return mesh.with_cell_data(k=np.linspace(1e-5, 1e-4, mesh.n_cells))


def _two_wedge_layers() -> HydroMesh:
    second = WEDGE_COLUMN + [0.0, 0.0, 1.0]
    vertices = np.vstack([WEDGE_COLUMN, second[3:]])
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(CellBlock(CellType.WEDGE, [[0, 1, 2, 3, 4, 5], [3, 4, 5, 6, 7, 8]]),),
        cell_data={"layer": np.array([1.0, 2.0])},
        point_data={"head": np.arange(9.0)},
    )


@pytest.mark.parametrize(
    "build", [_triangles, _grid_in_lambert93, _two_wedge_layers], ids=["triangles", "grid", "3d"]
)
def test_a_mesh_written_as_vtu_reads_back_with_its_cells_and_fields(tmp_path: Path, build) -> None:
    original = build()

    path = write_vtu(tmp_path / "mesh.vtu", original)
    recovered = read_vtu(path)

    assert path == (tmp_path / "mesh.vtu").resolve()
    assert recovered.cell_types == original.cell_types
    np.testing.assert_array_equal(recovered.flat_connectivity, original.flat_connectivity)
    np.testing.assert_array_equal(recovered.vertices[:, : original.ndim], original.vertices)
    for name, values in original.cell_data.items():
        np.testing.assert_array_equal(recovered.cell_data[name], values)
    for name, values in original.point_data.items():
        np.testing.assert_array_equal(recovered.point_data[name], values)


@pytest.mark.xfail(reason="read_vtu keeps the zero z meshio adds to a planar mesh", strict=True)
def test_a_planar_mesh_written_as_vtu_reads_back_planar(tmp_path: Path) -> None:
    recovered = read_vtu(write_vtu(tmp_path / "mesh.vtu", _triangles()))

    assert recovered.ndim == 2
