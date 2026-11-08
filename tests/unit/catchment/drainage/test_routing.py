"""Route a per-cell release down a receiver graph, and say how much of the catchment it drains.

The contract this file exists for: at the outlet cell the routed value IS the
domain sum. A per-cell discharge that does not reproduce the series the whole
catchment already produces is wrong, whatever else it gets right.

The graphs come from the descent D that a backend builds on a structured mesh,
``descent.metric.graph``. The largest drainable share is read on the value
that ``upstream_area`` returns, and no module keeps it between calls.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.catchment.drainage.descent import descent_basin
from hydromodpy.catchment.drainage.distance import shared_node_adjacency
from hydromodpy.catchment.drainage.graph import (
    build_downhill_graph,
    cell_adjacency_from_face_connectivity,
)
from hydromodpy.catchment.drainage.routing import (
    UpstreamArea,
    largest_drainable_share,
    route_release_to_discharge,
    upstream_area,
)
from hydromodpy.solver.modflow_common.flow_directions import build_solver_mesh_descent
from tests._helpers.solver_meshes import solver_mesh_from_structured_arrays
from tests._helpers.ugrid_meshes import quad_mesh

_NROW, _NCOL = 3, 3


def _model(top: np.ndarray, base_level: np.ndarray | None = None) -> SimpleNamespace:
    """A structured model whose top D is built on, as a backend build does."""
    nrow, ncol = top.shape
    mesh = solver_mesh_from_structured_arrays(
        nrow=nrow, ncol=ncol, top=top, botm=np.full((1, nrow, ncol), -10.0)
    )
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=base_level)
    return SimpleNamespace(solver_mesh=mesh, descent=descent, graph=descent.metric.graph)


def _cell_areas(model: SimpleNamespace) -> np.ndarray:
    return np.asarray(model.solver_mesh.cell_areas(), dtype=float).reshape(-1)


def _south_sloping_top() -> np.ndarray:
    """Every row drains to the row below, so cell (2, 1) collects the grid."""
    return np.array([[30.0, 29.0, 30.0], [20.0, 19.0, 20.0], [10.0, 1.0, 10.0]], dtype=float)


def _all(n: int = _NROW * _NCOL) -> np.ndarray:
    return np.ones(n, dtype=bool)


# -- The release ---------------------------------------------------------------


def test_the_outlet_collects_every_release_of_the_catchment() -> None:
    """routed(outlet) == the catchment sum, when the graph has ONE sink."""
    model = _model(_south_sloping_top())
    release = np.arange(1.0, _NROW * _NCOL + 1.0)

    accumulated = route_release_to_discharge(release, model.graph, catchment_mask=_all())

    assert accumulated[int(np.argmax(accumulated))] == pytest.approx(release.sum())


def test_an_interior_cell_carries_only_what_is_upstream_of_it() -> None:
    model = _model(_south_sloping_top())
    release = np.ones(_NROW * _NCOL)

    accumulated = route_release_to_discharge(release, model.graph, catchment_mask=_all())

    assert accumulated.max() == pytest.approx(release.sum())
    assert accumulated.min() < accumulated.max()


def test_cells_outside_the_catchment_release_nothing_into_it() -> None:
    """The mesh is a buffered box; the neighboring basins must not be counted."""
    model = _model(_south_sloping_top())
    mask = _all()
    mask[:_NCOL] = False  # drop the northern row from the catchment

    accumulated = route_release_to_discharge(
        np.ones(_NROW * _NCOL), model.graph, catchment_mask=mask
    )

    assert accumulated.max() == pytest.approx(float(mask.sum()))


def test_a_transient_stack_routes_every_timestep() -> None:
    model = _model(_south_sloping_top())
    stack = np.stack([np.ones(_NROW * _NCOL), 2.0 * np.ones(_NROW * _NCOL)])

    accumulated = route_release_to_discharge(stack, model.graph, catchment_mask=_all())

    assert accumulated.shape == stack.shape
    assert accumulated.max(axis=1) == pytest.approx([9.0, 18.0])


@pytest.mark.parametrize(
    ("mask", "message"),
    [
        (np.zeros(_NROW * _NCOL, dtype=bool), "holds no cell"),
        (np.ones(4, dtype=bool), "holds 4 cells and the release 9"),
    ],
    ids=["empty_mask", "wrong_size"],
)
def test_a_mask_that_does_not_fit_the_release_is_refused(mask: np.ndarray, message: str) -> None:
    model = _model(_south_sloping_top())

    with pytest.raises(ValueError, match=message):
        route_release_to_discharge(np.ones(_NROW * _NCOL), model.graph, catchment_mask=mask)


def test_what_leaves_through_the_sinks_is_everything_released() -> None:
    """The general identity, whatever the number of terminal cells."""
    model = _model(_south_sloping_top())
    release = np.arange(1.0, _NROW * _NCOL + 1.0)

    accumulated = route_release_to_discharge(release, model.graph, catchment_mask=_all())

    sinks = np.flatnonzero(np.asarray(model.graph.downstream) < 0)
    assert sinks.size
    assert float(accumulated[sinks].sum()) == pytest.approx(release.sum())
    assert float(accumulated.max()) <= release.sum() + 1e-12


def test_a_pit_of_the_top_does_not_hold_the_release_above_it() -> None:
    # A valley sloping to the south edge with a closed pit in its middle.
    rows, cols = np.mgrid[0:7, 0:7]
    top = 10.0 + 2.0 * (6 - rows) + np.abs(cols - 3)
    top[3, 3] = 0.0
    model = _model(top.astype(float))
    release = np.ones(49)

    accumulated = route_release_to_discharge(release, model.graph, catchment_mask=_all(49))

    pit = 3 * 7 + 3
    assert model.graph.downstream[pit] >= 0
    sinks = np.flatnonzero(np.asarray(model.graph.downstream) < 0)
    assert float(accumulated[sinks].sum()) == pytest.approx(release.sum())
    assert float(accumulated.max()) > float(accumulated[pit])


def test_a_stream_chd_inside_the_catchment_passes_the_water_to_the_outlet() -> None:
    # A valley sloping south, its river column held by a stream-role CHD that
    # carries all the release, as the release union counts it.
    n = 11
    rows, cols = np.mgrid[0:n, 0:n]
    top = 50.0 + 2.0 * np.abs(cols - 5) + 1.0 * (n - 1 - rows)
    river = (cols == 5).reshape(-1)
    model = _model(top.astype(float), base_level=river)
    release = np.where(river, 1.0, 0.0)

    accumulated = route_release_to_discharge(release, model.graph, catchment_mask=_all(n * n))

    outlet = int(np.argmax(accumulated))
    assert model.descent.constant_head[river].all()
    assert float(accumulated[outlet]) == pytest.approx(float(release.sum()))
    assert np.all(model.graph.downstream[river & (np.arange(n * n) != outlet)] >= 0)


# -- The upstream area ---------------------------------------------------------


def test_the_upstream_area_of_the_outlet_is_the_catchment_area() -> None:
    model = _model(_south_sloping_top())

    area = upstream_area(_cell_areas(model), model.graph, catchment_mask=_all())

    assert isinstance(area, UpstreamArea)
    assert area.m2.max() == pytest.approx(float(_cell_areas(model).sum()))


def test_the_upstream_area_follows_the_same_graph_as_the_release() -> None:
    """Runoff a gauge sees must be the runoff over the cells whose release it sees."""
    model = _model(_south_sloping_top())
    cell_areas = _cell_areas(model)

    area = upstream_area(cell_areas, model.graph, catchment_mask=_all())
    counts = route_release_to_discharge(np.ones(_NROW * _NCOL), model.graph, catchment_mask=_all())

    assert area.m2 == pytest.approx(counts * float(cell_areas[0]))


# -- The largest drainable share -----------------------------------------------
#
# The valley's talweg runs along the grid diagonal. The descent D of the model,
# D8 on quads, drains it whole. A steepest descent over shared edges on the
# unfilled top cannot follow it: that graph, built here by hand, is the
# fragmented one. A share far below one is a disagreement between the graph and
# the delineated basin, so it is stated, and a graph that drains its basin
# stays silent.

_N = 30
_CELL_SIZE = 75.0


def _diagonal_top() -> np.ndarray:
    """A V-shaped valley whose talweg runs along the grid diagonal."""
    rows, cols = np.meshgrid(np.arange(_N), np.arange(_N), indexing="ij")
    return 100.0 + 0.5 * np.abs(rows - cols) + 0.01 * (rows + cols)


def _diagonal_model() -> SimpleNamespace:
    return _model(_diagonal_top())


def _shared_edge_graph(model: SimpleNamespace):
    """Steepest descent of the unfilled top over shared edges: it cannot go diagonal."""
    mesh = model.solver_mesh
    top = np.asarray(mesh.top, dtype=float).reshape(-1)
    return build_downhill_graph(
        top,
        np.asarray(mesh.planar_mesh.flat_connectivity, dtype=int),
        vertices=np.asarray(mesh.planar_mesh.vertices, dtype=float),
        centroids=np.asarray(mesh.cell_centers(), dtype=float),
        inactive_mask=~np.isfinite(top),
    )


def test_a_graph_that_drains_its_basin_has_a_share_of_one_and_does_not_warn(caplog) -> None:
    model = _diagonal_model()

    with caplog.at_level(logging.WARNING):
        area = upstream_area(_cell_areas(model), model.graph, catchment_mask=_all(_N * _N))

    assert area.largest_drainable_share == pytest.approx(1.0)
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


def test_a_fragmented_graph_has_a_share_far_from_one_and_warns_without_refusing(caplog) -> None:
    model = _diagonal_model()

    with caplog.at_level(logging.WARNING):
        area = upstream_area(
            _cell_areas(model), _shared_edge_graph(model), catchment_mask=_all(_N * _N)
        )

    assert area.largest_drainable_share is not None and area.largest_drainable_share < 0.5
    assert area.m2.shape == (_N * _N,)
    assert "different drainage" in caplog.text


def test_the_share_is_the_one_the_direct_computation_gives() -> None:
    model = _diagonal_model()
    graph = _shared_edge_graph(model)
    mask = _all(_N * _N)
    areas = _cell_areas(model)
    accumulated = route_release_to_discharge(areas, graph, catchment_mask=mask)

    area = upstream_area(areas, graph, catchment_mask=mask)

    assert area.largest_drainable_share == pytest.approx(
        largest_drainable_share(areas, accumulated, mask)
    )
    np.testing.assert_array_equal(area.m2, accumulated)


def test_two_calls_keep_their_own_share() -> None:
    model = _diagonal_model()
    areas, mask = _cell_areas(model), _all(_N * _N)

    drained = upstream_area(areas, model.graph, catchment_mask=mask)
    fragmented = upstream_area(areas, _shared_edge_graph(model), catchment_mask=mask)

    assert drained.largest_drainable_share == pytest.approx(1.0)
    assert fragmented.largest_drainable_share < 0.5


def test_a_catchment_without_area_has_no_share() -> None:
    model = _model(_south_sloping_top())
    areas = np.zeros(_NROW * _NCOL)

    assert upstream_area(areas, model.graph, catchment_mask=_all()).largest_drainable_share is None


def test_the_basin_of_d_as_the_mask_drains_to_exactly_its_area(caplog) -> None:
    """The catchment is the basin of D: the largest accumulation is its area, share one."""
    model = _diagonal_model()
    areas = _cell_areas(model)
    talweg_cell = 10 * _N + 10
    basin = descent_basin(
        model.descent,
        cell_area_m2=areas,
        near=tuple(model.solver_mesh.cell_centers()[talweg_cell]),
    )

    with caplog.at_level(logging.WARNING):
        area = upstream_area(areas, model.graph, catchment_mask=basin.mask)

    assert 0 < int(basin.mask.sum()) < _N * _N
    assert float(np.max(area.m2)) == pytest.approx(basin.area_m2, abs=1e-9)
    assert area.largest_drainable_share == pytest.approx(1.0, abs=1e-12)
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


# A descent over shared edges cannot follow a talweg that runs diagonally.
#
# This pins a measurement, because the consequence is silent and large. The
# per-cell discharge once rode a downhill graph whose neighbor rule defaulted to
# shared edges; it now rides the descent D, D8 on quads. On a square grid a
# diagonal valley has no axis-aligned downhill step, so a shared-edge accumulation
# fragments instead of reaching the outlet.
#
# Measured on a real Nancon run at the basin outlet before this was pinned: the
# cell the gauge falls in drained 0.107 km2 of a 64.631 km2 catchment, two tenths of
# a per cent, which is the same failure on real topography. Flipping the default
# would change every stream-network calibration in the repository, so it is a
# decision and not a fix; what belongs here is the number nobody should have to
# re-derive.


def _largest_accumulated_share(*, diagonal_neighbors: bool) -> float:
    vertices, connectivity = quad_mesh(_N, _N, cell_size=_CELL_SIZE)
    top = _diagonal_top().reshape(-1)
    adjacency = (
        shared_node_adjacency(connectivity, n_cells=top.size)
        if diagonal_neighbors
        else cell_adjacency_from_face_connectivity(connectivity, n_cells=top.size)
    )
    graph = build_downhill_graph(top, connectivity, vertices=vertices, adjacency=adjacency)
    areas = np.full(top.size, _CELL_SIZE * _CELL_SIZE)
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


def test_the_run_states_what_its_graph_can_actually_drain(caplog) -> None:
    """A ratio far below one is an internal disagreement, not a preference.

    The delineation produces a basin every drop leaves by one cell, so the largest
    accumulation on a graph that drains that basin equals its area. The run says
    the ratio out loud, which turns a graph that cannot drain the basin from a
    silent error into a reported one: no threshold is involved, the two numbers
    are simply printed next to each other.
    """
    vertices, connectivity = quad_mesh(_N, _N, cell_size=_CELL_SIZE)
    top = _diagonal_top().reshape(-1)
    areas = np.full(top.size, _CELL_SIZE * _CELL_SIZE)
    mask = np.ones(top.size, dtype=bool)
    adjacency = cell_adjacency_from_face_connectivity(connectivity, n_cells=top.size)
    graph = build_downhill_graph(top, connectivity, vertices=vertices, adjacency=adjacency)
    accumulated = route_release_to_discharge(areas, graph, catchment_mask=mask)

    with caplog.at_level(logging.INFO):
        ratio = largest_drainable_share(areas, accumulated, mask)

    assert ratio == pytest.approx(0.066, abs=0.005)
    assert "different drainage" in caplog.text


def test_a_graph_that_drains_the_basin_reports_one() -> None:
    vertices, connectivity = quad_mesh(_N, _N, cell_size=_CELL_SIZE)
    top = _diagonal_top().reshape(-1)
    areas = np.full(top.size, _CELL_SIZE * _CELL_SIZE)
    mask = np.ones(top.size, dtype=bool)
    graph = build_downhill_graph(
        top,
        connectivity,
        vertices=vertices,
        adjacency=shared_node_adjacency(connectivity, n_cells=top.size),
    )
    accumulated = route_release_to_discharge(areas, graph, catchment_mask=mask)

    assert largest_drainable_share(areas, accumulated, mask) == pytest.approx(1.0)
