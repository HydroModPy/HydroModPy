"""Directed-edge lookup of a triangulation, and the fan of triangles around a node.

The lookup answers which triangle lies on the left of an edge ``a -> b``. The fan walks
clockwise around a node from one triangle to the one left of the edge towards another node.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.mesh.engines.face_families import edge_lookup

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
