"""A .msh file read for a mesh keeps the reader order and its named line groups."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hydromodpy.core.exceptions import MeshRequestError
from hydromodpy.spatial.mesh.gmsh_grid.gmsh_reader import read_gmsh_2d_mesh
from hydromodpy.spatial.mesh.planning.input_mesh import domain_polygon_of, read_input_triangulation

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
