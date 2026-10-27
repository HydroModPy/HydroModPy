"""Read, check and write the planar meshes of Gmsh, through meshio or the ASCII 2.2 reader."""

from __future__ import annotations

from pathlib import Path

import meshio
import numpy as np
import pytest

from hydromodpy.spatial.mesh.gmsh_grid import gmsh_reader
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


# -- the ASCII 2.2 fallback reader ---------------------------------------------

NODES_22 = ["$Nodes", "5", "1 0 0 0", "2 1 0 0", "3 1 1 0", "4 0 1 0", "5 2 0 0", "$EndNodes"]


def _msh22(tmp_path: Path, elements: list[str], *, nodes: list[str] = NODES_22) -> Path:
    """Write a hand-made ``.msh`` 2.2 body without its ``$MeshFormat`` header.

    meshio refuses such a file, so ``read_gmsh_2d_mesh`` reads it with its own
    ASCII parser.
    """
    lines = [*nodes, "$Elements", str(len(elements)), *elements, "$EndElements"]
    path = tmp_path / "hand_made.msh"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# Element lines: id, type (15 point, 1 line, 2 triangle, 3 quad), tag count, tags, nodes.
POINT = "1 15 2 0 1 1"
EDGE = "2 1 2 0 1 1 2"
TRIANGLES = ["3 2 2 0 1 1 2 3", "4 2 2 0 1 1 3 4"]
QUAD = "5 3 2 0 1 2 5 3 3"


def test_a_msh22_file_meshio_refuses_is_read_by_the_ascii_fallback(tmp_path):
    path = _msh22(tmp_path, [POINT, EDGE, *TRIANGLES])

    mesh_data = read_gmsh_2d_mesh(path)

    assert mesh_data.cell_type == "triangle"
    assert mesh_data.connectivity.tolist() == [[0, 1, 2], [0, 2, 3]]
    np.testing.assert_array_equal(mesh_data.points_xy[:4], [[0, 0], [1, 0], [1, 1], [0, 1]])
    assert mesh_data.source_path == path.resolve()


def test_the_fallback_keeps_the_projection_file_next_to_the_mesh(tmp_path):
    from pyproj import CRS

    path = _msh22(tmp_path, TRIANGLES)
    projection_path(path).write_text(CRS.from_epsg(2154).to_wkt(), encoding="utf-8")

    assert CRS.from_wkt(read_gmsh_2d_mesh(path).crs_wkt) == CRS.from_epsg(2154)


def test_the_fallback_refuses_mixed_cells_unless_one_type_is_asked(tmp_path):
    quad = "5 3 2 0 1 2 5 3 4"
    path = _msh22(tmp_path, [*TRIANGLES, quad])

    with pytest.raises(ValueError, match="through meshio or the ASCII Gmsh fallback") as caught:
        read_gmsh_2d_mesh(path)
    assert "Mixed 2D cell types" in str(caught.value.__cause__)

    quads = read_gmsh_2d_mesh(path, cell_type="quad")
    assert quads.cell_type == "quadrilateral"
    assert quads.connectivity.tolist() == [[1, 4, 2, 3]]


@pytest.mark.parametrize(
    ("elements", "nodes", "reason"),
    [
        (
            TRIANGLES,
            [n for n in NODES_22 if not n.startswith("$")],
            "Missing Gmsh section '$Nodes'",
        ),
        (TRIANGLES, [*NODES_22[:2], "1 0 0", *NODES_22[3:]], "Invalid node line"),
        (TRIANGLES, [*NODES_22[:6], "7 2 0 0", NODES_22[-1]], "contiguous node ids"),
        (["3 2"], NODES_22, "expected at least 3 tokens"),
        ([QUAD.replace(" 3 2 0 1 ", " 2 2 0 1 ")], NODES_22, "expected 3 node ids"),
        ([POINT, EDGE], NODES_22, "No supported 2D triangle/quadrilateral elements"),
    ],
    ids=["no nodes", "short node line", "gap in node ids", "short element", "bad width", "no cell"],
)
def test_a_corrupt_msh_file_names_what_both_readers_missed(tmp_path, elements, nodes, reason):
    path = _msh22(tmp_path, elements, nodes=nodes)

    with pytest.raises(ValueError, match="through meshio or the ASCII Gmsh fallback") as caught:
        read_gmsh_2d_mesh(path)

    assert reason in str(caught.value.__cause__)


def test_without_meshio_an_ascii_msh_file_is_still_read(tmp_path, monkeypatch):
    path = _msh22(tmp_path, TRIANGLES)

    def no_meshio():
        raise ImportError("meshio is required")

    monkeypatch.setattr(gmsh_reader, "_require_meshio", no_meshio)

    assert read_gmsh_2d_mesh(path).connectivity.tolist() == [[0, 1, 2], [0, 2, 3]]
    with pytest.raises(ImportError, match="meshio is required"):
        read_gmsh_2d_mesh(tmp_path / "catchment.vtu")


def test_a_file_meshio_cannot_read_and_not_a_msh_is_refused(tmp_path):
    path = tmp_path / "mesh.vtu"
    path.write_text("not a mesh", encoding="utf-8")

    with pytest.raises(ValueError, match="Could not read planar mesh"):
        read_gmsh_2d_mesh(path)


# -- the mesh payload ------------------------------------------------------------


def test_an_unknown_cell_type_lists_the_names_it_takes():
    with pytest.raises(
        ValueError, match="Unsupported planar cell type 'hexagon'. Allowed: .*quads"
    ):
        normalize_cell_type("hexagon")


@pytest.mark.parametrize(
    ("points", "blocks", "reason"),
    [
        (np.zeros((3, 3)), "one triangle", "points_xy must have shape"),
        (np.zeros((3, 2)), "none", "cell_blocks cannot be empty"),
        (np.zeros((2, 2)), "one triangle", "outside points_xy"),
    ],
)
def test_a_mesh_payload_checks_its_points_and_its_cells(points, blocks, reason):
    cell_blocks = (
        (GmshCellBlock(cell_type="triangle", connectivity=[[0, 1, 2]]),)
        if blocks == "one triangle"
        else ()
    )
    with pytest.raises(ValueError, match=reason):
        GmshMeshData(points_xy=points, cell_blocks=cell_blocks)


def test_a_cell_block_checks_the_width_of_its_rows():
    with pytest.raises(
        ValueError, match=r"quadrilateral connectivity must have shape \(n_cells, 4\)"
    ):
        GmshCellBlock(cell_type="quad", connectivity=[[0, 1, 2]])


def test_a_meshio_mesh_gives_its_supported_cells_only(tmp_path):
    points = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
    lines_only = meshio.Mesh(points=points, cells=[("line", [[0, 1]])])
    flat = meshio.Mesh(points=points[:, :1], cells=[("triangle", [[0, 1, 2]])])
    with_lines = meshio.Mesh(points=points, cells=[("line", [[0, 1]]), ("triangle", [[0, 1, 2]])])

    with pytest.raises(ValueError, match="does not contain supported"):
        meshio_to_mesh_data(lines_only)
    with pytest.raises(ValueError, match="at least x and y"):
        meshio_to_mesh_data(flat)
    with pytest.raises(ValueError, match="does not contain supported"):
        meshio_to_mesh_data(with_lines, cell_type="quad")
    assert meshio_to_mesh_data(with_lines).n_cells == 1
    assert meshio_to_mesh_data(with_lines).n_nodes == 3
