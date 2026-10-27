"""A triangulation read from a ``.msh`` file, for a mesh that does not generate its own.

The file keeps the reader order of its nodes and triangles, and its named line
groups become edge labels. Only ASCII format 2.2 is read. The triangles are
refused on a T-junction, a vertex inside the edge of a triangle that does not
hold it, which leaves a boundary closed to flow inside the domain; the message
gives where. Two vertices at the same place cut the same crack and are
reported, not refused. The outline of a planar mesh, holes included, comes from
its boundary edges.
"""

from __future__ import annotations

import re
from pathlib import Path

import meshio
import numpy as np
import pytest
import shapely
from shapely.geometry import Polygon

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.engines.voronoi.tessellation import voronoi_planar_mesh
from hydromodpy.spatial.mesh.io.msh import read_gmsh_2d_mesh, write_msh
from hydromodpy.spatial.mesh.model.cell_types import CellType
from hydromodpy.spatial.mesh.model.derived_geometry import derive_geometry
from hydromodpy.spatial.mesh.model.hydro_mesh import CellBlock, HydroMesh
from hydromodpy.spatial.mesh.planning.input_mesh import (
    check_triangulation,
    domain_polygon_from_mesh,
    domain_polygon_of,
    read_input_triangulation,
)

_REPO = Path(__file__).resolve().parents[4]
_GALLERY_MSH = (
    _REPO
    / "examples/projects/07_mesh_gallery/10km2/mesh_s3_10km2_outlet_1_geology_rivers_buffer30/bundle/mesh_2d.msh"
)

_NAMES = """$PhysicalNames
3
1 7 "river::1"
1 8 "west"
2 9 "zone::domain"
$EndPhysicalNames
"""

# A 100 m square with a centre node; node tags are not contiguous on purpose.
_BODY = """$Nodes
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


def _write(path: Path, *, names: bool, header: str = "2.2 0 8") -> Path:
    path.write_text(
        f"$MeshFormat\n{header}\n$EndMeshFormat\n" + (_NAMES if names else "") + _BODY,
        encoding="utf-8",
    )
    return path


def test_named_line_groups_become_edge_labels(tmp_path: Path) -> None:
    path = _write(tmp_path / "mesh.msh", names=True)
    triangulation = read_input_triangulation(path)
    reference = read_gmsh_2d_mesh(path, cell_type="triangle")
    np.testing.assert_array_equal(triangulation.vertices, reference.points_xy)
    np.testing.assert_array_equal(triangulation.triangles, reference.connectivity)
    assert sorted(triangulation.edge_labels) == ["river::1", "west"]
    np.testing.assert_array_equal(triangulation.edge_labels["river::1"], [[0, 4], [4, 2]])
    np.testing.assert_array_equal(triangulation.edge_labels["west"], [[3, 0]])


@pytest.mark.parametrize(
    ("shared", "river"),
    [
        ('1 6 "river::1"', [[0, 4], [4, 2], [1, 2]]),
        ('2 7 "river::1"', [[0, 4], [4, 2]]),
    ],
    ids=["two line tags", "a line and a surface"],
)
def test_a_name_two_groups_share_labels_the_lines_of_every_tag(
    tmp_path: Path, shared: str, river: list[list[int]]
) -> None:
    """Every dimension-1 tag named ``river::1`` labels its lines, whatever group shares the name."""
    names = _NAMES.replace("3\n", "4\n", 1).replace('1 8 "west"\n', f'1 8 "west"\n{shared}\n')
    path = tmp_path / "mesh.msh"
    path.write_text("$MeshFormat\n2.2 0 8\n$EndMeshFormat\n" + names + _BODY, encoding="utf-8")

    triangulation = read_input_triangulation(path)

    assert {name: pairs.tolist() for name, pairs in triangulation.edge_labels.items()} == {
        "river::1": river,
        "west": [[3, 0]],
    }


def test_without_physical_names_no_edge_is_labelled(tmp_path: Path) -> None:
    path = _write(tmp_path / "mesh.msh", names=False)
    triangulation = read_input_triangulation(path)
    reference = read_gmsh_2d_mesh(path, cell_type="triangle")
    np.testing.assert_array_equal(triangulation.vertices, reference.points_xy)
    np.testing.assert_array_equal(triangulation.triangles, reference.connectivity)
    assert dict(triangulation.edge_labels) == {}


def test_a_binary_or_newer_file_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path / "mesh.msh", names=True, header="4.1 0 8")
    with pytest.raises(MeshRequestError, match="only ASCII format 2.2"):
        read_input_triangulation(path)


def test_a_binary_file_of_format_2_2_is_refused(tmp_path: Path) -> None:
    triangle = HydroMesh(
        vertices=np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]]),
        cell_blocks=(CellBlock(CellType.TRIANGLE, [[0, 1, 2]]),),
    )
    path = write_msh(tmp_path / "binary.msh", triangle, file_format="gmsh22")

    with pytest.raises(MeshRequestError, match="only ASCII format 2.2"):
        read_input_triangulation(path)


def test_the_domain_is_the_outline_of_the_triangles(tmp_path: Path) -> None:
    triangulation = read_input_triangulation(_write(tmp_path / "mesh.msh", names=True))
    domain = domain_polygon_of(triangulation)
    assert domain.area == pytest.approx(10_000.0)
    assert domain.bounds == (0.0, 0.0, 100.0, 100.0)


@pytest.mark.skipif(not _GALLERY_MSH.exists(), reason="gallery mesh not in this checkout")
def test_a_gallery_mesh_reads_in_the_reader_order() -> None:
    triangulation = read_input_triangulation(_GALLERY_MSH)
    reference = read_gmsh_2d_mesh(_GALLERY_MSH, cell_type="triangle")
    np.testing.assert_array_equal(triangulation.vertices, reference.points_xy)
    np.testing.assert_array_equal(triangulation.triangles, reference.connectivity)
    assert "river::trace" in triangulation.edge_labels
    assert len(triangulation.edge_labels["river::trace"]) > 0


# A 100 m square cut into a lower and an upper half along y = 50. The lower half
# is two triangles; the upper half is three, with a vertex at (50, 50) that the
# lower triangles do not hold.
_T_VERTICES = np.array(
    [
        [0.0, 0.0],
        [100.0, 0.0],
        [100.0, 50.0],
        [0.0, 50.0],
        [50.0, 50.0],
        [0.0, 100.0],
        [100.0, 100.0],
    ]
)
_T_TRIANGLES = np.array([[0, 1, 2], [0, 2, 3], [3, 4, 5], [4, 6, 5], [4, 2, 6]])


def _square(*, duplicate: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Four triangles around a centre node; ``duplicate`` gives the last two their own centre."""
    vertices = [[0.0, 0.0], [100.0, 0.0], [100.0, 100.0], [0.0, 100.0], [50.0, 50.0]]
    triangles = [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]]
    if duplicate:
        vertices.append([50.0, 50.0])
        triangles[2:] = [[2, 3, 5], [3, 0, 5]]
    return np.array(vertices), np.array(triangles)


def test_a_conforming_triangulation_passes(caplog) -> None:
    vertices, triangles = _square()
    with caplog.at_level("WARNING"):
        check_triangulation(vertices, triangles, source="square")
    assert caplog.text == ""


def test_a_t_junction_is_refused_with_its_coordinates() -> None:
    with pytest.raises(MeshRequestError, match=r"T-junctions\), at \(50\.000, 50\.000\)"):
        check_triangulation(_T_VERTICES, _T_TRIANGLES, source="t-mesh")


def test_duplicate_vertices_are_reported_and_kept(caplog) -> None:
    vertices, triangles = _square(duplicate=True)
    with caplog.at_level("WARNING"):
        check_triangulation(vertices, triangles, source="cracked")
    assert "1 pairs of vertices" in caplog.text
    assert "(50.000, 50.000)" in caplog.text


def test_the_reader_runs_the_check(tmp_path: Path) -> None:
    nodes = "\n".join(f"{i + 1} {x} {y} 0" for i, (x, y) in enumerate(_T_VERTICES.tolist()))
    elements = "\n".join(
        f"{i + 1} 2 2 1 1 {a + 1} {b + 1} {c + 1}" for i, (a, b, c) in enumerate(_T_TRIANGLES)
    )
    path = tmp_path / "t.msh"
    path.write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n"
        f"$Nodes\n{len(_T_VERTICES)}\n{nodes}\n$EndNodes\n"
        f"$Elements\n{len(_T_TRIANGLES)}\n{elements}\n$EndElements\n",
        encoding="utf-8",
    )
    with pytest.raises(MeshRequestError, match="T-junction"):
        read_input_triangulation(path)


def test_blank_lines_between_the_sections_are_skipped(tmp_path: Path) -> None:
    path = tmp_path / "mesh.msh"
    path.write_text(
        "$MeshFormat\n2.2 0 8\n$EndMeshFormat\n\n"
        + _NAMES
        + "\n"
        + _BODY.replace("$Elements\n", "\n$Elements\n"),
        encoding="utf-8",
    )

    triangulation = read_input_triangulation(path)

    assert len(triangulation.triangles) == 4
    assert sorted(triangulation.edge_labels) == ["river::1", "west"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (_BODY.split("$Elements")[0], "does not contain supported 2D cell blocks"),
        ("", "must expose at least x and y"),
        (
            "$Elements" + _BODY.split("$Elements")[1],
            "through meshio or the ASCII Gmsh fallback: Missing Gmsh section '$Nodes'",
        ),
    ],
    ids=["no elements", "no section", "elements without nodes"],
)
def test_a_file_whose_sections_are_incomplete_is_refused(
    tmp_path: Path, text: str, message: str
) -> None:
    path = tmp_path / "mesh.msh"
    path.write_text(f"$MeshFormat\n2.2 0 8\n$EndMeshFormat\n{text}", encoding="utf-8")

    with pytest.raises(
        MeshRequestError, match=f"cannot be read as a triangulation: .*{re.escape(message)}"
    ):
        read_input_triangulation(path)


def test_the_fallback_names_a_missing_elements_section(tmp_path: Path, monkeypatch) -> None:
    """meshio reads a file without ``$Elements``; the fallback, when it reads, names the section."""
    path = tmp_path / "mesh.msh"
    nodes = "$Nodes\n3\n1 0 0 0\n2 1 0 0\n3 0 1 0\n$EndNodes\n"
    path.write_text(f"$MeshFormat\n2.2 0 8\n$EndMeshFormat\n{nodes}", encoding="utf-8")

    def meshio_fails(*_args, **_kwargs):
        raise ValueError("meshio fails")

    monkeypatch.setattr(meshio, "read", meshio_fails)

    with pytest.raises(
        MeshRequestError,
        match=r"cannot be read as a triangulation: .* fallback: Missing Gmsh section '\$Elements'",
    ):
        read_input_triangulation(path)


def test_a_file_without_a_format_section_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "mesh.msh"
    path.write_text(_NAMES + _BODY, encoding="utf-8")

    with pytest.raises(MeshRequestError, match=r"has no \$MeshFormat section"):
        read_input_triangulation(path)


def test_a_file_neither_reader_reads_is_refused_with_the_reason(tmp_path: Path) -> None:
    path = _write(tmp_path / "mesh.msh", names=True)
    path.write_text(path.read_text().replace("1 1 2 8 1 40 10", "1 1 0 40 10"), encoding="utf-8")

    with pytest.raises(
        MeshRequestError,
        match="through meshio or the ASCII Gmsh fallback: .*contiguous node ids starting at 1",
    ):
        read_input_triangulation(path)


# -- outline of a mesh ---------------------------------------------------------

_DOMAIN = Polygon([(0.0, 0.0), (1000.0, 0.0), (1000.0, 1000.0), (0.0, 1000.0)])


def _jittered_seeds(n_side: int = 12) -> np.ndarray:
    rng = np.random.default_rng(0)
    grid = np.linspace(50.0, 950.0, n_side)
    xx, yy = np.meshgrid(grid, grid)
    return np.c_[xx.ravel(), yy.ravel()] + rng.uniform(-25.0, 25.0, (n_side * n_side, 2))


def test_the_outline_of_a_mesh_keeps_the_hole_of_its_domain() -> None:
    hole = Polygon([(400.0, 400.0), (600.0, 400.0), (600.0, 600.0), (400.0, 600.0)])
    domain = _DOMAIN.difference(hole)
    seeds = _jittered_seeds()
    seeds = seeds[shapely.contains_xy(domain, *seeds.T)]
    mesh = voronoi_planar_mesh(seeds, domain)

    outline = domain_polygon_from_mesh(mesh)

    assert len(outline.interiors) == 1
    assert outline.area == pytest.approx(derive_geometry(mesh).areas.sum(), rel=1e-9)


def test_a_mesh_without_a_boundary_edge_has_no_outline() -> None:
    """Every edge of a triangle written twice is shared by two cells, so none bounds the mesh."""
    vertices = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    doubled = HydroMesh(
        vertices=vertices,
        cell_blocks=(
            CellBlock(cell_type=CellType.TRIANGLE, connectivity=np.array([[0, 1, 2]] * 2)),
        ),
    )

    with pytest.raises(ValueError, match="could not reconstruct a domain polygon"):
        domain_polygon_from_mesh(doubled)
