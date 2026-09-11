"""A descent over shared edges cannot follow a talweg that runs diagonally.

This pins a measurement, because the consequence is silent and large. Both the
stream-network criterion and the per-cell discharge ride the same downhill graph,
and its neighbour rule defaults to shared edges. On a square grid a diagonal
valley has no axis-aligned downhill step, so the accumulation fragments instead of
reaching the outlet.

Measured on a real Nancon run at the basin outlet before this was pinned: the
cell the gauge falls in drained 0.107 km2 of a 64.631 km2 catchment, two tenths of
a per cent, which is the same failure on real topography. Flipping the default
would change every stream-network calibration in the repository, so it is a
decision and not a fix; what belongs here is the number nobody should have to
re-derive.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.field_routing import (
    build_downhill_graph,
    cell_adjacency_from_face_connectivity,
)
from hydromodpy.core.topographic_distance import shared_node_adjacency
from hydromodpy.solver.modflow_common.discharge_routing import route_release_to_discharge
from tests._helpers.ugrid_meshes import quad_mesh

N = 30
CELL_SIZE = 75.0


def _diagonal_valley() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """A V-shaped valley whose talweg runs along the grid diagonal."""
    vertices, connectivity = quad_mesh(N, N, cell_size=CELL_SIZE)
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    top = (100.0 + 0.5 * np.abs(rows - cols) + 0.01 * (rows + cols)).reshape(-1)
    return vertices, connectivity, top


def _largest_accumulated_share(*, diagonal_neighbors: bool) -> float:
    vertices, connectivity, top = _diagonal_valley()
    adjacency = (
        shared_node_adjacency(connectivity, n_cells=top.size)
        if diagonal_neighbors
        else cell_adjacency_from_face_connectivity(connectivity, n_cells=top.size)
    )
    graph = build_downhill_graph(top, connectivity, vertices=vertices, adjacency=adjacency)
    areas = np.full(top.size, CELL_SIZE * CELL_SIZE)
    accumulated = route_release_to_discharge(
        areas, graph, catchment_mask=np.ones(top.size, dtype=bool)
    )
    return float(accumulated.max() / areas.sum())


def test_shared_nodes_bring_the_whole_valley_to_one_cell() -> None:
    assert _largest_accumulated_share(diagonal_neighbors=True) == pytest.approx(1.0)


def test_shared_edges_strand_most_of_it() -> None:
    # 6.6 per cent, on a surface whose every cell drains to the same diagonal.
    share = _largest_accumulated_share(diagonal_neighbors=False)
    assert share < 0.1
    assert share == pytest.approx(0.066, abs=0.005)


def test_the_two_rules_differ_by_more_than_an_order_of_magnitude() -> None:
    # The point of the gate: this is not a second-decimal choice.
    with_nodes = _largest_accumulated_share(diagonal_neighbors=True)
    with_edges = _largest_accumulated_share(diagonal_neighbors=False)
    assert with_nodes / with_edges > 10.0
