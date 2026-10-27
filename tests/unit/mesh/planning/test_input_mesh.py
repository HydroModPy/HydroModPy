"""A triangulation read from a ``.msh`` file, for a mesh that does not generate its own.

The file keeps the reader order of its nodes and triangles, and its named line
groups become edge labels. Only ASCII format 2.2 is read. The triangles are
refused on a T-junction, a vertex inside the edge of a triangle that does not
hold it, which leaves a boundary closed to flow inside the domain; the message
gives where. Two vertices at the same place cut the same crack and are
reported, not refused.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import read_gmsh_2d_mesh
from hydromodpy.spatial.mesh.planning.input_mesh import (
    check_triangulation,
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
        (_BODY.split("$Elements")[0], r"has no \$Elements section"),
    ],
    ids=["no elements"],
)
def test_a_file_whose_sections_are_incomplete_is_refused(
    tmp_path: Path, text: str, message: str
) -> None:
    path = tmp_path / "mesh.msh"
    path.write_text(f"$MeshFormat\n2.2 0 8\n$EndMeshFormat\n{text}", encoding="utf-8")

    with pytest.raises(MeshRequestError, match=message):
        read_input_triangulation(path)
