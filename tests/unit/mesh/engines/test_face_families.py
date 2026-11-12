"""Directed-edge lookup of a triangulation, and the fan of triangles around a node.

The lookup answers which triangle lies on the left of an edge ``a -> b``. The fan walks
clockwise around a node from one triangle to the one left of the edge towards another node.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.mesh.engines.face_families import box_side_edges, edge_lookup
from hydromodpy.mesh.planar.cell_types import CellType
from hydromodpy.mesh.planar.geometry import derive_geometry
from hydromodpy.mesh.planar.hydro_mesh import CellBlock, HydroMesh
from tests._helpers.mesh_cases import L93_ORIGIN

# A unit square cut into four triangles around the centre node 4 (m).
SQUARE = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.5, 0.5]])
AROUND_CENTRE = np.array([[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]])

FANS = [
    # Clockwise from triangle 0 around node 4 the triangles are 3, 2, then 1.
    pytest.param(AROUND_CENTRE, 2, [3, 2], id="stops at the edge towards node 2"),
    pytest.param(AROUND_CENTRE, 0, [], id="stop is the first corner"),
    pytest.param(AROUND_CENTRE[:3], 2, [], id="boundary reached first"),
    pytest.param(AROUND_CENTRE, 9, [], id="stop is not around the node"),
]


@pytest.mark.parametrize(("triangles", "stop", "fan"), FANS)
def test_fan_around_a_node(triangles: np.ndarray, stop: int, fan: list[int]) -> None:
    lookup = edge_lookup(SQUARE, triangles)

    assert lookup.fan(0, 4, stop) == fan


def test_clockwise_triangle_is_read_counter_clockwise() -> None:
    lookup = edge_lookup(SQUARE, np.array([[0, 4, 1]]))  # clockwise as given

    left = lookup.cell_left_of(np.array([0, 1, 4]), np.array([1, 4, 0]))

    np.testing.assert_array_equal(left, [0, 0, 0])
    np.testing.assert_array_equal(lookup.cell_left_of(np.array([1]), np.array([0])), [-1])


def _lattice(nx: int, ny: int, step: float) -> tuple[np.ndarray, np.ndarray]:
    # Vertices are numbered row by row from the south-west corner.
    x0, y0 = L93_ORIGIN
    vertices = np.array(
        [(x0 + step * i, y0 + step * j) for j in range(ny) for i in range(nx)], dtype=float
    )
    triangles = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            south_west, south_east = j * nx + i, j * nx + i + 1
            triangles += [
                (south_west, south_east, south_east + nx),
                (south_west, south_east + nx, south_west + nx),
            ]
    return vertices, np.asarray(triangles, dtype=np.int64)


def test_each_boundary_edge_joins_the_family_of_the_box_side_it_lies_on() -> None:
    # A 400 m by 200 m lattice: no side shares the length, the span or a bound of another.
    nx, ny = 5, 3
    vertices, triangles = _lattice(nx, ny, 100.0)
    geometry = derive_geometry(HydroMesh(vertices, (CellBlock(CellType.TRIANGLE, triangles),)))
    sides = {
        "boundary:west": [(j * nx, (j + 1) * nx) for j in range(ny - 1)],
        "boundary:east": [(j * nx + nx - 1, (j + 2) * nx - 1) for j in range(ny - 1)],
        "boundary:south": [(i, i + 1) for i in range(nx - 1)],
        "boundary:north": [((ny - 1) * nx + i, (ny - 1) * nx + i + 1) for i in range(nx - 1)],
    }

    families = box_side_edges(vertices, geometry, edge_lookup(vertices, triangles))

    assert [family.name for family in families] == list(sides)
    for family in families:
        edges = {frozenset(e) for e in zip(family.node_a.tolist(), family.node_b.tolist())}
        assert edges == {frozenset(e) for e in sides[family.name]}, family.name
        assert np.all(family.cell_b == -1), family.name
        start = vertices[family.node_a]
        tangent = vertices[family.node_b] - start
        offset = vertices[triangles[family.cell_a]].mean(axis=1) - start
        assert np.all(tangent[:, 0] * offset[:, 1] - tangent[:, 1] * offset[:, 0] > 0.0)
