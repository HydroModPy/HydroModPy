"""Read, check and write the planar meshes of Gmsh, through meshio or the ASCII 2.2 reader.

A ``.msh`` file reads into the payload ``GmshMeshData``, cells and named line
groups, or into a ``HydroMesh``, and a planar ``HydroMesh`` writes back to one,
with its projection file when it has a CRS.
"""

from __future__ import annotations

import re
from pathlib import Path

import meshio
import numpy as np
import pytest

from hydromodpy.mesh.io.msh import (
    GmshCellBlock,
    GmshMeshData,
    meshio_to_mesh_data,
    msh_format,
    normalize_cell_type,
    projection_path,
    read_gmsh_2d_mesh,
    read_msh,
    write_gmsh_2d_mesh,
    write_msh,
)
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh


def test_mixed_payload_has_no_cell_type():
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


def test_meshio_roundtrip(tmp_path):
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


def test_crs_projection_file_roundtrip(tmp_path):
    from pyproj import CRS

    path = write_gmsh_2d_mesh(tmp_path / "catchment.msh", _one_triangle(), crs="EPSG:2154")

    assert projection_path(path) == tmp_path / "catchment.prj"
    assert CRS.from_wkt(projection_path(path).read_text(encoding="utf-8")) == CRS.from_epsg(2154)
    reread = read_gmsh_2d_mesh(path)
    assert CRS.from_wkt(reread.crs_wkt) == CRS.from_epsg(2154)
    assert reread.n_cells == 1

    again = write_gmsh_2d_mesh(tmp_path / "copy.msh", reread)
    assert read_gmsh_2d_mesh(again).crs_wkt == reread.crs_wkt


def test_bad_crs_writes_nothing(tmp_path):
    from pyproj.exceptions import CRSError

    with pytest.raises(CRSError):
        write_gmsh_2d_mesh(tmp_path / "catchment.msh", _one_triangle(), crs="not a crs")

    assert not (tmp_path / "catchment.msh").exists()


NODES_22 = ["$Nodes", "5", "1 0 0 0", "2 1 0 0", "3 1 1 0", "4 0 1 0", "5 2 0 0", "$EndNodes"]


def _msh22(tmp_path: Path, elements: list[str] | None, *, nodes: list[str] = NODES_22) -> Path:
    """Write a hand-made ``.msh`` 2.2 body without its ``$MeshFormat`` header.

    meshio refuses such a file, so ``read_gmsh_2d_mesh`` reads it with its own
    ASCII parser. ``elements=None`` leaves the ``$Elements`` section out.
    """
    lines = list(nodes)
    if elements is not None:
        lines += ["$Elements", str(len(elements)), *elements, "$EndElements"]
    path = tmp_path / "hand_made.msh"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# Element lines: id, type (15 point, 1 line, 2 triangle, 3 quad), tag count, tags, nodes.
POINT = "1 15 2 0 1 1"
EDGE = "2 1 2 0 1 1 2"
TRIANGLES = ["3 2 2 0 1 1 2 3", "4 2 2 0 1 1 3 4"]
QUAD = "5 3 2 0 1 2 5 3 3"


def test_ascii_fallback_reads_msh22(tmp_path):
    path = _msh22(tmp_path, [POINT, EDGE, *TRIANGLES])

    mesh_data = read_gmsh_2d_mesh(path)

    assert mesh_data.cell_type == "triangle"
    assert mesh_data.connectivity.tolist() == [[0, 1, 2], [0, 2, 3]]
    np.testing.assert_array_equal(mesh_data.points_xy[:4], [[0, 0], [1, 0], [1, 1], [0, 1]])
    assert mesh_data.source_path == path.resolve()


def test_fallback_mixed_cells(tmp_path):
    quad = "5 3 2 0 1 2 5 3 4"
    path = _msh22(tmp_path, [*TRIANGLES, quad])

    with pytest.raises(
        ValueError, match="through meshio or the ASCII Gmsh fallback: Mixed 2D cell types"
    ):
        read_gmsh_2d_mesh(path)

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
        (None, NODES_22, "Missing Gmsh section '$Elements'"),
        (TRIANGLES, [*NODES_22[:2], "1 0 0", *NODES_22[3:]], "Invalid node line"),
        (TRIANGLES, [*NODES_22[:6], "7 2 0 0", NODES_22[-1]], "contiguous node ids"),
        (["3 2"], NODES_22, "expected at least 3 tokens"),
        ([QUAD.replace(" 3 2 0 1 ", " 2 2 0 1 ")], NODES_22, "expected 3 node ids"),
        ([POINT, EDGE], NODES_22, "No supported 2D triangle/quadrilateral elements"),
    ],
    ids=[
        "no nodes",
        "no elements",
        "short node line",
        "gap in node ids",
        "short element",
        "bad width",
        "no cell",
    ],
)
def test_corrupt_msh_refusals(tmp_path, elements, nodes, reason):
    path = _msh22(tmp_path, elements, nodes=nodes)

    with pytest.raises(
        ValueError, match=rf"through meshio or the ASCII Gmsh fallback: .*{re.escape(reason)}"
    ):
        read_gmsh_2d_mesh(path)


def test_fallback_line_groups(tmp_path):
    names = ["$PhysicalNames", "2", '1 7 "river::1"', '2 9 "zone"', "$EndPhysicalNames"]
    river = ["6 1 2 7 1 1 3", "7 1 2 7 1 3 4", "8 1 2 8 1 4 1", "9 1 0 2 3"]
    path = _msh22(tmp_path, [*river, *TRIANGLES], nodes=[*names, *NODES_22])

    mesh_data = read_gmsh_2d_mesh(path)

    assert list(mesh_data.line_groups) == ["river::1"]
    assert mesh_data.line_groups["river::1"].tolist() == [[0, 2], [2, 3]]
    assert mesh_data.connectivity.tolist() == [[0, 1, 2], [0, 2, 3]]


def test_unreadable_file_refused(tmp_path):
    path = tmp_path / "mesh.vtu"
    path.write_text("not a mesh", encoding="utf-8")

    with pytest.raises(ValueError, match="Could not read planar mesh"):
        read_gmsh_2d_mesh(path)


def test_unknown_cell_type_refused():
    with pytest.raises(
        ValueError, match="Unsupported planar cell type 'hexagon'. Allowed: .*quads"
    ):
        normalize_cell_type("hexagon")


ONE_TRIANGLE = (GmshCellBlock(cell_type="triangle", connectivity=[[0, 1, 2]]),)


@pytest.mark.parametrize(
    ("points", "blocks", "reason"),
    [
        pytest.param(np.zeros((3, 3)), ONE_TRIANGLE, "points_xy must have shape", id="3d points"),
        pytest.param(np.zeros((3, 2)), (), "cell_blocks cannot be empty", id="no block"),
        pytest.param(np.zeros((2, 2)), ONE_TRIANGLE, "outside points_xy", id="node past points"),
    ],
)
def test_payload_refusals(points, blocks, reason):
    with pytest.raises(ValueError, match=reason):
        GmshMeshData(points_xy=points, cell_blocks=blocks)


def test_block_width_refused():
    with pytest.raises(
        ValueError, match=r"quadrilateral connectivity must have shape \(n_cells, 4\)"
    ):
        GmshCellBlock(cell_type="quad", connectivity=[[0, 1, 2]])


def test_meshio_supported_cells(tmp_path):
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


_LINES_22 = """$MeshFormat
2.2 0 8
$EndMeshFormat
$PhysicalNames
3
1 7 "river::1"
1 8 "west"
2 9 "zone::domain"
$EndPhysicalNames
$Nodes
5
10 0 0 0
20 100 0 0
30 100 100 0
40 0 100 0
50 50 50 0
$EndNodes
$Elements
9
1 1 2 8 1 40 10
2 1 2 7 2 10 50
3 1 2 7 2 50 30
4 1 2 6 3 20 30
5 15 2 9 1 10
6 2 2 9 1 10 20 50
7 2 2 9 1 20 30 50
8 2 2 9 1 30 40 50
9 2 2 9 1 40 10 50
$EndElements
"""


_SQUARE_22 = """$Nodes
4
1 0 0 0
2 1 0 0
3 1 1 0
4 0 1 0
$EndNodes
$Elements
4
1 1 2 {line_a} 1 1 2
2 1 2 {line_b} 2 2 3
3 2 2 {surface} 1 1 2 3
4 2 2 {surface} 1 1 3 4
$EndElements
"""

_SHARED_NAMES = {
    "two line tags": (['1 5 "river"', '1 6 "river"', '2 1 "domain"'], (5, 6, 1)),
    "a line and a surface": (['1 5 "river"', '2 5 "river"'], (5, 5, 5)),
}
"""Physical names that two groups share, and the tags of the two lines and of the triangles."""


def _write_shared_names(tmp_path: Path, case: str) -> Path:
    """Write a gmsh 2.2 square whose two lines carry a physical name another group shares."""
    names, (line_a, line_b, surface) = _SHARED_NAMES[case]
    path = tmp_path / "shared.msh"
    path.write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n"
        + "\n".join(["$PhysicalNames", str(len(names)), *names, "$EndPhysicalNames"])
        + "\n"
        + _SQUARE_22.format(line_a=line_a, line_b=line_b, surface=surface),
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize("reader", ["meshio", "fallback"])
@pytest.mark.parametrize("case", list(_SHARED_NAMES))
def test_shared_name_keeps_all_tags(tmp_path, monkeypatch, case, reader):
    """The name of a line comes from the dimension-1 entries of ``$PhysicalNames``, by tag."""
    path = _write_shared_names(tmp_path, case)
    meshio.read(path)  # meshio reads the file, so the fallback runs only when forced
    if reader == "fallback":

        def meshio_fails(*_args, **_kwargs):
            raise ValueError("meshio fails")

        monkeypatch.setattr(meshio, "read", meshio_fails)

    line_groups = read_gmsh_2d_mesh(path).line_groups

    assert {name: pairs.tolist() for name, pairs in line_groups.items()} == {
        "river": [[0, 1], [1, 2]]
    }


def test_meshio_line_names():
    mesh = meshio.Mesh(
        points=np.zeros((3, 3)),
        cells=[("line", [[0, 1], [1, 2]]), ("triangle", [[0, 1, 2]])],
        cell_data={"gmsh:physical": [np.array([7, 8]), np.array([9])]},
        field_data={"river": np.array([7, 1]), "domain": np.array([9, 2])},
    )

    line_groups = meshio_to_mesh_data(mesh).line_groups

    assert {name: pairs.tolist() for name, pairs in line_groups.items()} == {"river": [[0, 1]]}


def test_line_group_outside_nodes():
    with pytest.raises(ValueError, match="line groups reference node indices outside"):
        GmshMeshData(
            points_xy=np.zeros((3, 2)),
            cell_blocks=(GmshCellBlock("triangle", [[0, 1, 2]]),),
            line_groups={"river": [[0, 3]]},
        )


def test_msh_format_line(tmp_path):
    path = tmp_path / "square.msh"
    path.write_text("$Comments\nmade by hand\n$EndComments\n" + _LINES_22, encoding="utf-8")
    binary = write_gmsh_2d_mesh(tmp_path / "binary.msh", _one_triangle(), file_format="gmsh")

    assert msh_format(path) == "2.2 0 8"
    assert msh_format(binary) == "4.1 1 8"
    assert msh_format(_msh22(tmp_path, TRIANGLES)) is None


def test_empty_format_section(tmp_path):
    path = tmp_path / "empty.msh"
    path.write_text("$MeshFormat\n\n", encoding="utf-8")

    assert msh_format(path) is None


def _two_triangles() -> HydroMesh:
    return HydroMesh(
        vertices=np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [0.0, 10.0]]),
        cell_blocks=(CellBlock(CellType.TRIANGLE, [[0, 1, 2], [0, 2, 3]]),),
    )


def test_hydro_mesh_msh_with_crs(tmp_path):
    from pyproj import CRS

    path = write_msh(tmp_path / "mesh_2d.msh", _two_triangles(), crs="EPSG:2154")

    assert CRS.from_wkt(read_gmsh_2d_mesh(path).crs_wkt) == CRS.from_epsg(2154)
    np.testing.assert_array_equal(read_msh(path).vertices, _two_triangles().vertices)


@pytest.mark.parametrize(
    ("mesh", "reason"),
    [
        (
            HydroMesh(
                vertices=np.zeros((3, 3)), cell_blocks=(CellBlock(CellType.TRIANGLE, [[0, 1, 2]]),)
            ),
            "planar HydroMesh",
        ),
        (
            HydroMesh(
                vertices=np.zeros((5, 2)),
                cell_blocks=(CellBlock(CellType.POLYGON, (np.arange(5),)),),
            ),
            "not polygon cells",
        ),
    ],
    ids=["with a z", "polygons"],
)
def test_write_refusals(tmp_path, mesh, reason):
    with pytest.raises(ValueError, match=reason):
        write_msh(tmp_path / "mesh.msh", mesh)
