"""Unit tests for injecting a prebuilt cell adjacency into the downhill graph."""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.field_routing import (
    build_downhill_graph,
    cell_adjacency_from_face_connectivity,
)
from tests._helpers.ugrid_meshes import king_adjacency, quad_mesh


def test_injected_adjacency_reaches_the_diagonal_receiver() -> None:
    # Plane dropping one unit per step to the east and to the south. The
    # steepest slope out of the upper-left cell is its diagonal neighbor, which
    # two quads sharing a single node never expose to shared-edge adjacency.
    vertices, connectivity = quad_mesh(3, 3)
    reference = np.array([-(row + col) for row in range(3) for col in range(3)], dtype=float)

    shared_edge = build_downhill_graph(reference, connectivity, vertices=vertices)
    shared_node = build_downhill_graph(
        reference,
        connectivity,
        vertices=vertices,
        adjacency=king_adjacency(3, 3),
    )

    assert shared_edge.downstream[0] in (1, 3)
    assert shared_node.downstream[0] == 4


def test_default_adjacency_matches_the_shared_edge_builder() -> None:
    vertices, connectivity = quad_mesh(4, 5)
    rng = np.random.default_rng(11)
    reference = rng.normal(100.0, 5.0, 20)

    implicit = build_downhill_graph(reference, connectivity, vertices=vertices)
    explicit = build_downhill_graph(
        reference,
        connectivity,
        vertices=vertices,
        adjacency=cell_adjacency_from_face_connectivity(connectivity, n_cells=20),
    )

    assert np.array_equal(implicit.downstream, explicit.downstream)
    assert np.array_equal(implicit.order, explicit.order)
    assert np.array_equal(implicit.active, explicit.active)


def test_adjacency_length_is_validated() -> None:
    _, connectivity = quad_mesh(2, 2)
    reference = np.arange(4, dtype="float64")

    with pytest.raises(ValueError, match="adjacency must have 4 entries"):
        build_downhill_graph(reference, connectivity, adjacency=[set(), set()])

    # The guard sits before the all-inactive shortcut, so a wrong length is
    # reported whatever the surface looks like.
    with pytest.raises(ValueError, match="adjacency must have 4 entries"):
        build_downhill_graph(
            np.full(4, np.nan),
            connectivity,
            adjacency=[set(), set()],
        )
