"""D is stored as receivers and a filled surface, and the graph comes back from them.

A reader routes on D without the mesh geometry: ordering the cells by descending
filled surface puts every donor before its receiver, because every link of D
strictly descends on that surface.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.core.descent import descent_from_stored_mesh, descent_graph
from hydromodpy.core.field_routing import accumulate_on_downhill_graph
from tests._helpers.ugrid_meshes import quad_mesh
from tests.unit.core._descent_meshes import grid_descent

PIT_TOP = np.array(
    [
        [9.0, 8.0, 7.0, 8.0],
        [8.0, 5.0, 4.0, 7.0],
        [7.0, 4.0, 1.0, 6.0],
        [6.0, 5.0, 4.0, 5.0],
    ]
)
"""A bowl: the middle cell is a pit of the top, deeper than its whole ring."""


def test_the_graph_rebuilt_from_two_arrays_routes_like_the_graph_d_built() -> None:
    descent = grid_descent(PIT_TOP, base_level=np.eye(1, 16, 3, dtype=bool).ravel())
    flux = np.linspace(1.0, 2.0, 16)

    stored = descent_graph(descent.receiver, descent.surface)

    np.testing.assert_array_equal(stored.downstream, descent.metric.graph.downstream)
    np.testing.assert_array_equal(
        accumulate_on_downhill_graph(stored, flux),
        accumulate_on_downhill_graph(descent.metric.graph, flux),
    )


def test_every_donor_comes_before_its_receiver_in_the_rebuilt_order() -> None:
    descent = grid_descent(PIT_TOP)

    graph = descent_graph(descent.receiver, descent.surface)

    position = np.empty(16, dtype=int)
    position[graph.order] = np.arange(graph.order.size)
    for cell in graph.order.tolist():
        target = int(graph.downstream[cell])
        if target >= 0:
            assert position[cell] < position[target]


def test_a_cell_off_the_graph_is_not_routable() -> None:
    top = np.array([[3.0, 2.0, 1.0], [4.0, np.nan, 2.0]])
    routable = np.isfinite(top).ravel()

    descent = grid_descent(top, routable=routable)
    graph = descent_graph(descent.receiver, descent.surface)

    assert not graph.active[4]
    assert 4 not in graph.order.tolist()
    assert graph.active.sum() == 5


def test_receivers_and_surface_of_different_sizes_are_refused() -> None:
    with pytest.raises(ValueError, match="receivers"):
        descent_graph(np.zeros(4, dtype=int), np.zeros(5))


def test_a_descent_rebuilt_from_a_stored_mesh_has_no_pin_no_channel_and_fills_the_pit() -> None:
    vertices, connectivity = quad_mesh(4, 4)

    descent = descent_from_stored_mesh(PIT_TOP.ravel(), connectivity, vertices)

    assert descent.n_channel == 0
    assert descent.n_pinned == 0
    assert descent.n_raised >= 1
    assert descent.diagonal_neighbors
    rim = np.ones((4, 4), dtype=bool)
    rim[1:3, 1:3] = False
    assert descent.base_level[rim.ravel()].all()
    assert not descent.base_level[~rim.ravel()].any()
