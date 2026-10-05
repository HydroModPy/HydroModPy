"""Without pins nor channel, D is the criterion's flood and steepest descent.

The reference is the pipeline D ran before it held its own flood: the stream
criterion's fill on the descended graph, then the steepest-descent receivers on
the filled copy. Copy, receivers and raised count must match on every mesh the
descent tests use.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.depression_filling import fill_depressions_on_graph
from hydromodpy.core.descent import build_descent
from hydromodpy.core.field_routing import (
    cell_adjacency_from_face_connectivity,
    domain_edge_cells,
)
from hydromodpy.core.topographic_distance import (
    build_downslope_metric,
    resolve_diagonal_neighbors,
    shared_node_adjacency,
)
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.core._descent_meshes import grid_centres, triangle_mesh

N = 12


def _reference(top, connectivity, vertices, centroids, routable, diagonal):
    n_cells = top.size
    on_graph = routable & np.isfinite(top)
    use = resolve_diagonal_neighbors(connectivity, n_cells=n_cells, requested=diagonal)
    adjacency = (
        shared_node_adjacency(connectivity, n_cells=n_cells)
        if use
        else cell_adjacency_from_face_connectivity(connectivity, n_cells=n_cells)
    )
    seeds = domain_edge_cells(connectivity, on_graph)
    fill = fill_depressions_on_graph(np.where(on_graph, top, np.nan), adjacency, seeds)
    metric = build_downslope_metric(
        fill.surface,
        connectivity,
        vertices=vertices,
        centroids=centroids,
        inactive_mask=~on_graph,
        diagonal_neighbors=use,
        adjacency=adjacency,
    )
    return fill, metric.graph.downstream


def _quad_case(seed: int, hole: bool, flat_share: float):
    vertices, connectivity = quad_mesh(N, N)
    rng = np.random.default_rng(seed)
    top = rng.uniform(0.0, 20.0, N * N)
    # Rounded plateaus give the flood ties to break, as a flat DEM does.
    plateau = rng.random(N * N) < flat_share
    top[plateau] = np.round(top[plateau] / 5.0) * 5.0
    routable = np.ones(N * N, dtype=bool)
    if hole:
        routable[N * N // 2 : N * N // 2 + 3] = False
    return top, connectivity, vertices, grid_centres(N, N), routable


def _triangle_case(seed: int):
    vertices, connectivity, centroids = triangle_mesh(N, N)
    top = np.random.default_rng(seed).uniform(0.0, 20.0, connectivity.shape[0])
    return top, connectivity, vertices, centroids, np.ones(top.size, dtype=bool)


@pytest.mark.parametrize(
    ("case", "diagonal"),
    [
        (_quad_case(7, False, 0.0), True),
        (_quad_case(7, True, 0.0), True),
        (_quad_case(11, False, 0.6), True),
        (_quad_case(11, True, 0.6), False),
        (_triangle_case(7), True),
        (_triangle_case(13), True),
    ],
)
def test_the_copy_and_the_receivers_are_unchanged(case, diagonal: bool) -> None:
    top, connectivity, vertices, centroids, routable = case
    fill, receivers = _reference(top, connectivity, vertices, centroids, routable, diagonal)

    descent = build_descent(
        top,
        connectivity,
        vertices=vertices,
        centroids=centroids,
        routable=routable,
        diagonal_neighbors=diagonal,
    )

    np.testing.assert_array_equal(descent.receiver, receivers)
    np.testing.assert_array_equal(descent.surface, fill.surface)
    assert descent.n_raised == fill.n_filled
    assert descent.n_channel == 0
    assert descent.n_pinned == 0
