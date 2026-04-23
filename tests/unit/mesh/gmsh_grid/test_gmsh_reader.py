from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import (
    GmshCellBlock,
    GmshMeshData,
    meshio_to_mesh_data,
    normalize_cell_type,
    read_gmsh_2d_mesh,
    write_gmsh_2d_mesh,
)


def test_normalize_cell_type_supports_gmsh_aliases():
    assert normalize_cell_type("triangle") == "triangle"
    assert normalize_cell_type("quad") == "quadrilateral"
    assert normalize_cell_type("quadrilateral") == "quadrilateral"


def test_gmsh_mesh_data_rejects_mixed_cell_types_for_one_planar_mesh():
    mesh_data = GmshMeshData(
        points_xy=np.array(
            [
                [0.0, 0.0],
                [1.0, 0.0],
                [1.0, 1.0],
                [0.0, 1.0],
            ],
            dtype=float,
        ),
        cell_blocks=(
            GmshCellBlock(cell_type="triangle", connectivity=np.array([[0, 1, 2]], dtype=int)),
            GmshCellBlock(cell_type="quad", connectivity=np.array([[0, 1, 2, 3]], dtype=int)),
        ),
    )

    with pytest.raises(ValueError, match="mixed"):
        _ = mesh_data.cell_type


def test_meshio_roundtrip_and_mixed_selection():
    meshio = pytest.importorskip("meshio")

    points = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 1.0, 0.0],
            [0.0, 1.0, 0.0],
            [2.0, 0.0, 0.0],
            [2.0, 1.0, 0.0],
        ],
        dtype=float,
    )
    triangles = np.array([[0, 1, 2], [0, 2, 3]], dtype=int)
    quads = np.array([[1, 4, 5, 2]], dtype=int)
    mesh = meshio.Mesh(points=points, cells=[("triangle", triangles), ("quad", quads)])

    with pytest.raises(ValueError, match="Mixed 2D cell types"):
        meshio_to_mesh_data(mesh)

    selected = meshio_to_mesh_data(mesh, cell_type="quadrilateral")
    assert selected.cell_type == "quadrilateral"
    assert selected.n_cells == 1
    assert selected.connectivity.shape == (1, 4)

    output_dir = Path.cwd() / "scratch_tests" / "gmsh_reader" / "runtime"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "planar_triangles.vtu"
    write_gmsh_2d_mesh(
        path,
        GmshMeshData(
            points_xy=np.asarray(points[:, :2], dtype=float),
            cell_blocks=(GmshCellBlock(cell_type="triangle", connectivity=triangles),),
        ),
    )
    reread = read_gmsh_2d_mesh(path)
    assert reread.cell_type == "triangle"
    assert reread.n_cells == 2
    assert np.allclose(reread.points_xy, points[:, :2])
