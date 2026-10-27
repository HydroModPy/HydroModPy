from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import (
    GmshCellBlock,
    GmshMeshData,
    meshio_to_mesh_data,
    normalize_cell_type,
    projection_path,
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


def test_meshio_roundtrip_and_mixed_selection(tmp_path):
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

    path = tmp_path / "planar_triangles.vtu"
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


def _one_triangle() -> GmshMeshData:
    return GmshMeshData(
        points_xy=np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]),
        cell_blocks=(GmshCellBlock(cell_type="triangle", connectivity=np.array([[0, 1, 2]])),),
    )


def test_a_mesh_written_with_a_crs_gets_a_projection_file_read_back(tmp_path):
    from pyproj import CRS

    path = write_gmsh_2d_mesh(tmp_path / "catchment.msh", _one_triangle(), crs="EPSG:2154")

    assert projection_path(path) == tmp_path / "catchment.prj"
    assert CRS.from_wkt(projection_path(path).read_text(encoding="utf-8")) == CRS.from_epsg(2154)
    reread = read_gmsh_2d_mesh(path)
    assert CRS.from_wkt(reread.crs_wkt) == CRS.from_epsg(2154)
    assert reread.n_cells == 1

    again = write_gmsh_2d_mesh(tmp_path / "copy.msh", reread)
    assert read_gmsh_2d_mesh(again).crs_wkt == reread.crs_wkt


def test_a_mesh_written_without_a_crs_gets_no_projection_file(tmp_path):
    path = write_gmsh_2d_mesh(tmp_path / "catchment.msh", _one_triangle())

    assert not projection_path(path).exists()
    assert read_gmsh_2d_mesh(path).crs_wkt is None


def test_an_empty_projection_file_reads_as_no_crs(tmp_path):
    path = write_gmsh_2d_mesh(tmp_path / "catchment.msh", _one_triangle())
    projection_path(path).write_text("\n", encoding="utf-8")

    assert read_gmsh_2d_mesh(path).crs_wkt is None


def test_a_crs_pyproj_cannot_read_is_refused_before_the_mesh_is_written(tmp_path):
    from pyproj.exceptions import CRSError

    with pytest.raises(CRSError):
        write_gmsh_2d_mesh(tmp_path / "catchment.msh", _one_triangle(), crs="not a crs")

    assert not (tmp_path / "catchment.msh").exists()
