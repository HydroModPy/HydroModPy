"""Route the per-cell release downstream, so a gauge is scored where it sits.

The contract this file exists for: at the outlet cell the routed value IS the
domain sum. A per-cell discharge that does not reproduce the series the whole
catchment already produces is wrong, whatever else it gets right.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow_common.discharge_routing import (
    flat_cell_index,
    route_release_to_discharge,
    routing_graph_for_model,
    upstream_area_m2,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

_NROW, _NCOL = 3, 3


def _model(top: np.ndarray) -> SimpleNamespace:
    """A 3x3 structured model whose top is the routing surface."""
    botm = np.full((_NROW, _NCOL), -10.0, dtype=float)
    mesh = SolverMesh.from_structured_arrays(
        nrow=_NROW,
        ncol=_NCOL,
        top=top,
        botm=np.stack([botm]),
    )
    return SimpleNamespace(solver_mesh=mesh)


def _south_sloping_top() -> np.ndarray:
    """Every row drains to the row below, so cell (2, 1) collects the grid."""
    return np.array(
        [
            [30.0, 29.0, 30.0],
            [20.0, 19.0, 20.0],
            [10.0, 1.0, 10.0],
        ],
        dtype=float,
    )


def _outlet_index(model: SimpleNamespace, accumulated: np.ndarray) -> int:
    del model
    return int(np.argmax(accumulated))


def test_the_outlet_collects_every_release_of_the_catchment():
    """routed(outlet) == the catchment sum, when the graph has ONE sink.

    A catchment whose routing graph terminates in several cells splits the sum
    between them; the general statement is the mass conservation below, and this
    fixture is the single-sink special case.
    """
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    release = np.arange(1.0, _NROW * _NCOL + 1.0)
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=mask)

    assert accumulated[_outlet_index(model, accumulated)] == pytest.approx(release.sum())


def test_an_interior_cell_carries_only_what_is_upstream_of_it():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    release = np.ones(_NROW * _NCOL)
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=mask)

    outlet = accumulated[_outlet_index(model, accumulated)]
    assert outlet == pytest.approx(release.sum())
    # No cell can carry more than the outlet, and at least one carries less.
    assert accumulated.max() == pytest.approx(outlet)
    assert accumulated.min() < outlet


def test_cells_outside_the_catchment_release_nothing_into_it():
    """The mesh is a buffered box; the neighbouring basins must not be counted."""
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    release = np.ones(_NROW * _NCOL)
    mask = np.ones(_NROW * _NCOL, dtype=bool)
    mask[:_NCOL] = False  # drop the northern row from the catchment

    accumulated = route_release_to_discharge(release, graph, catchment_mask=mask)

    assert accumulated.max() == pytest.approx(float(mask.sum()))


def test_a_transient_stack_routes_every_timestep():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    stack = np.stack([np.ones(_NROW * _NCOL), 2.0 * np.ones(_NROW * _NCOL)])
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    accumulated = route_release_to_discharge(stack, graph, catchment_mask=mask)

    assert accumulated.shape == stack.shape
    assert accumulated.max(axis=1) == pytest.approx([9.0, 18.0])


def test_the_upstream_area_of_the_outlet_is_the_catchment_area():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    areas = upstream_area_m2(model, graph, catchment_mask=mask)

    assert areas.max() == pytest.approx(float(model.solver_mesh.cell_areas().sum()))


def test_the_upstream_area_follows_the_same_graph_as_the_release():
    """Runoff a gauge sees must be the runoff over the cells whose release it sees."""
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    mask = np.ones(_NROW * _NCOL, dtype=bool)
    cell_areas = model.solver_mesh.cell_areas()

    areas = upstream_area_m2(model, graph, catchment_mask=mask)
    counts = route_release_to_discharge(np.ones(_NROW * _NCOL), graph, catchment_mask=mask)

    assert areas == pytest.approx(counts * float(cell_areas[0]))


def test_a_mask_that_holds_no_cell_is_refused():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)

    with pytest.raises(ValueError, match="holds no cell"):
        route_release_to_discharge(
            np.ones(_NROW * _NCOL), graph, catchment_mask=np.zeros(_NROW * _NCOL, dtype=bool)
        )


def test_a_mask_of_the_wrong_size_is_refused():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)

    with pytest.raises(ValueError, match="holds 4 cells and the release 9"):
        route_release_to_discharge(
            np.ones(_NROW * _NCOL), graph, catchment_mask=np.ones(4, dtype=bool)
        )


def test_a_structured_cell_maps_to_its_flat_index():
    model = _model(_south_sloping_top())

    assert flat_cell_index(model, (0, 2, 1)) == 2 * _NCOL + 1


def test_a_cell_outside_the_mesh_is_refused():
    model = _model(_south_sloping_top())

    with pytest.raises(ValueError, match="outside the 9 cells"):
        flat_cell_index(model, (0, 9, 9))


def test_a_model_without_a_mesh_says_so():
    with pytest.raises(ValueError, match="carries none"):
        routing_graph_for_model(SimpleNamespace(solver_mesh=None))


def test_what_leaves_through_the_sinks_is_everything_released():
    """The general identity, whatever the number of terminal cells."""
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    release = np.arange(1.0, _NROW * _NCOL + 1.0)
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=mask)

    sinks = np.flatnonzero(np.asarray(graph.downstream) < 0)
    assert sinks.size
    assert float(accumulated[sinks].sum()) == pytest.approx(release.sum())


def test_no_cell_carries_more_than_the_catchment_released():
    model = _model(_south_sloping_top())
    graph = routing_graph_for_model(model)
    release = np.arange(1.0, _NROW * _NCOL + 1.0)
    mask = np.ones(_NROW * _NCOL, dtype=bool)

    accumulated = route_release_to_discharge(release, graph, catchment_mask=mask)

    assert float(accumulated.max()) <= release.sum() + 1e-12
