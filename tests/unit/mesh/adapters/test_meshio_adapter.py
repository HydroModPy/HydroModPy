"""A HydroMesh goes to a meshio mesh and comes back with its cells and its fields."""

from __future__ import annotations

import meshio
import numpy as np
import pytest

from hydromodpy.spatial.mesh import CellBlock, CellType, HydroMesh
from hydromodpy.spatial.mesh.adapters.meshio_adapter import from_meshio, to_meshio

HEX_AND_WEDGE_VERTICES = np.array(
    [
        [0, 0, 0],
        [1, 0, 0],
        [1, 1, 0],
        [0, 1, 0],
        [0, 0, 1],
        [1, 0, 1],
        [1, 1, 1],
        [0, 1, 1],
        [2, 0, 0],
        [2, 0, 1],
    ],
    dtype=float,
)


def _assert_same_cells(back: HydroMesh, original: HydroMesh) -> None:
    assert back.cell_types == original.cell_types
    for got, expected in zip(back.cell_blocks, original.cell_blocks, strict=True):
        assert [list(c) for c in got.connectivity] == [list(c) for c in expected.connectivity]


def _triangles() -> HydroMesh:
    verts = np.array([[0, 0], [1, 0], [0.5, 1], [1.5, 1]], dtype=float)
    return HydroMesh(
        vertices=verts,
        cell_blocks=(CellBlock(CellType.TRIANGLE, np.array([[0, 1, 2], [1, 3, 2]])),),
        cell_data={"k": np.array([1.0, 2.0])},
    )


def _quad_and_triangle() -> HydroMesh:
    vertices = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [2, 0]], dtype=float)
    return HydroMesh(
        vertices=vertices,
        cell_blocks=(
            CellBlock(CellType.QUADRILATERAL, [[0, 1, 2, 3]]),
            CellBlock(CellType.TRIANGLE, [[1, 4, 2]]),
        ),
        cell_data={"k": np.array([1.0, 2.0])},
        point_data={"z": np.arange(5.0)},
    )


def _hexahedron_and_wedge() -> HydroMesh:
    return HydroMesh(
        vertices=HEX_AND_WEDGE_VERTICES,
        cell_blocks=(
            CellBlock(CellType.HEXAHEDRON, [[0, 1, 2, 3, 4, 5, 6, 7]]),
            CellBlock(CellType.WEDGE, [[1, 8, 2, 5, 9, 6]]),
        ),
        cell_data={"k": np.array([1.0, 2.0])},
        point_data={"head": np.arange(10.0)},
    )


def test_a_triangle_mesh_comes_back_with_its_cell_field() -> None:
    original = _triangles()

    recovered = from_meshio(to_meshio(original))

    _assert_same_cells(recovered, original)
    np.testing.assert_array_equal(recovered.vertices[:, :2], original.vertices)
    np.testing.assert_array_equal(recovered.cell_data["k"], [1.0, 2.0])


def test_a_planar_mesh_gets_a_zero_z_for_meshio() -> None:
    points = to_meshio(_triangles()).points

    assert points.shape == (4, 3)
    assert not points[:, 2].any()


@pytest.mark.parametrize(
    "build", [_quad_and_triangle, _hexahedron_and_wedge], ids=["mixed 2d", "mixed 3d"]
)
def test_mixed_cells_come_back_block_by_block_with_their_fields(build) -> None:
    original = build()

    recovered = from_meshio(to_meshio(original))

    _assert_same_cells(recovered, original)
    np.testing.assert_array_equal(recovered.vertices[:, : original.ndim], original.vertices)
    np.testing.assert_array_equal(recovered.cell_data["k"], original.cell_data["k"])
    for name, values in original.point_data.items():
        np.testing.assert_array_equal(recovered.point_data[name], values)


def test_polygons_of_one_arity_come_back_as_polygons() -> None:
    vertices = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [2, 0], [2, 1]], dtype=float)
    original = HydroMesh(
        vertices=vertices,
        cell_blocks=(
            CellBlock(CellType.POLYGON, (np.array([0, 1, 2, 3]), np.array([1, 4, 5, 2]))),
        ),
        cell_data={"k": np.array([1.0, 2.0])},
    )

    recovered = from_meshio(to_meshio(original))

    _assert_same_cells(recovered, original)
    np.testing.assert_array_equal(recovered.cell_data["k"], [1.0, 2.0])


@pytest.mark.xfail(
    raises=ValueError,
    reason="to_meshio hands meshio one polygon block of mixed arity, which meshio refuses",
)
def test_a_voronoi_mesh_of_ragged_polygons_goes_to_meshio() -> None:
    vertices = np.array([[1, 0], [1, 1], [0, 1], [-0.3, 0.5], [0, 0], [2, 0], [2, 1]], dtype=float)
    original = HydroMesh(
        vertices=vertices,
        cell_blocks=(
            CellBlock(CellType.POLYGON, (np.array([0, 1, 2, 3, 4]), np.array([0, 5, 6, 1]))),
        ),
    )

    _assert_same_cells(from_meshio(to_meshio(original)), original)


def test_a_cell_field_that_is_not_one_value_per_cell_stays_behind() -> None:
    mesh = _triangles().with_cell_data(k=np.array([1.0, 2.0]))
    mesh = HydroMesh(
        vertices=mesh.vertices,
        cell_blocks=mesh.cell_blocks,
        cell_data={**mesh.cell_data, "disv_cell_center": np.array([[0.5, 0.3], [1.0, 0.7]])},
    )

    assert set(to_meshio(mesh).cell_data) == {"k"}


def test_line_and_vertex_blocks_are_left_out_with_their_fields() -> None:
    mesh = meshio.Mesh(
        points=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], dtype=float),
        cells=[("vertex", [[0]]), ("line", [[0, 1]]), ("triangle", [[0, 1, 2]])],
        cell_data={"k": [np.array([9.0]), np.array([5.0]), np.array([7.0])]},
    )

    recovered = from_meshio(mesh)

    assert recovered.cell_types == (CellType.TRIANGLE,)
    np.testing.assert_array_equal(recovered.cell_data["k"], [7.0])


def test_a_cell_field_given_as_one_array_is_not_read() -> None:
    mesh = meshio.Mesh(
        points=np.array([[0, 0], [1, 0], [0, 1]], dtype=float), cells=[("triangle", [[0, 1, 2]])]
    )
    mesh.cell_data = {"k": np.array([7.0])}

    assert from_meshio(mesh).cell_data == {}


def test_a_cell_field_with_no_block_is_not_read() -> None:
    mesh = meshio.Mesh(
        points=np.array([[0, 0], [1, 0], [0, 1]], dtype=float), cells=[("triangle", [[0, 1, 2]])]
    )
    mesh.cell_data = {"k": []}

    assert from_meshio(mesh).cell_data == {}


def test_a_mesh_with_only_lines_raises() -> None:
    mesh = meshio.Mesh(points=np.array([[0, 0], [1, 0]], dtype=float), cells=[("line", [[0, 1]])])

    with pytest.raises(ValueError, match="no supported cell types"):
        from_meshio(mesh)


def test_points_on_one_axis_raise() -> None:
    mesh = meshio.Mesh(points=np.array([[0.0], [1.0], [2.0]]), cells=[("triangle", [[0, 1, 2]])])

    with pytest.raises(ValueError, match="at least 2D points"):
        from_meshio(mesh)
