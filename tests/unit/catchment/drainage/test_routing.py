"""Route a per-cell release down a receiver graph, and say how much of the catchment it drains.

At the outlet cell the routed value is the domain sum (same unit as the release),
and the upstream area (m2) is the same routing of the cell areas. The graphs come
from the descent D that a backend builds on a structured mesh, ``descent.metric.graph``.
The largest drainable share is read on the value that ``upstream_area`` returns.
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

N_SMALL = 3  # cells per side of the small grid
N_SMALL_CELLS = N_SMALL * N_SMALL
N_DIAGONAL = 30  # cells per side of the diagonal valley
CELL_SIZE_M = 75.0


def structured_model(top, base_level=None):
    """A structured model whose top D is built on, as a backend build does."""
    nrow, ncol = top.shape
    mesh = solver_mesh_from_structured_arrays(
        nrow=nrow, ncol=ncol, top=top, botm=np.full((1, nrow, ncol), -10.0)
    )
    descent = build_solver_mesh_descent(mesh, lake_cells_by_lake={}, base_level_mask=base_level)
    return SimpleNamespace(solver_mesh=mesh, descent=descent, graph=descent.metric.graph)


def cell_areas(model):
    return np.asarray(model.solver_mesh.cell_areas(), dtype=float).reshape(-1)


def all_cells(n_cells=N_SMALL_CELLS):
    return np.ones(n_cells, dtype=bool)


def south_slope():
    """Every row drains to the row below, so cell (2, 1) collects the grid."""
    top = np.array([[30.0, 29.0, 30.0], [20.0, 19.0, 20.0], [10.0, 1.0, 10.0]])
    return structured_model(top)


def diagonal_top():
    """A V-shaped valley (m) whose talweg runs along the grid diagonal."""
    rows, cols = np.meshgrid(np.arange(N_DIAGONAL), np.arange(N_DIAGONAL), indexing="ij")
    return 100.0 + 0.5 * np.abs(rows - cols) + 0.01 * (rows + cols)


def diagonal_model():
    return structured_model(diagonal_top())


def shared_edge_graph(model):
    """Steepest descent of the unfilled top over shared edges, it cannot go diagonal."""
    mesh = model.solver_mesh
    top = np.asarray(mesh.top, dtype=float).reshape(-1)
    return build_downhill_graph(
        top,
        np.asarray(mesh.planar_mesh.flat_connectivity, dtype=int),
        vertices=np.asarray(mesh.planar_mesh.vertices, dtype=float),
        centroids=np.asarray(mesh.cell_centers(), dtype=float),
        inactive_mask=~np.isfinite(top),
    )


def diagonal_valley_on_quads(diagonal_neighbors):
    """Areas (m2), mask and downhill graph of the diagonal valley on a quad mesh."""
    vertices, connectivity = quad_mesh(N_DIAGONAL, N_DIAGONAL, cell_size=CELL_SIZE_M)
    top = diagonal_top().reshape(-1)
    if diagonal_neighbors:
        adjacency = shared_node_adjacency(connectivity, n_cells=top.size)
    else:
        adjacency = cell_adjacency_from_face_connectivity(connectivity, n_cells=top.size)
    graph = build_downhill_graph(top, connectivity, vertices=vertices, adjacency=adjacency)
    areas = np.full(top.size, CELL_SIZE_M * CELL_SIZE_M)
    return areas, np.ones(top.size, dtype=bool), graph


def test_outlet_collects_every_release():
    release = np.arange(1.0, N_SMALL_CELLS + 1.0)

    accumulated = route_release_to_discharge(
        release, south_slope().graph, catchment_mask=all_cells()
    )

    assert accumulated[int(np.argmax(accumulated))] == pytest.approx(release.sum())


def test_interior_cell_carries_only_upstream():
    release = np.ones(N_SMALL_CELLS)

    accumulated = route_release_to_discharge(
        release, south_slope().graph, catchment_mask=all_cells()
    )

    assert accumulated.max() == pytest.approx(release.sum())
    assert accumulated.min() < accumulated.max()


def test_cells_outside_catchment_release_nothing():
    # The mesh is a buffered box, the neighboring basins must not be counted.
    mask = all_cells()
    mask[:N_SMALL] = False  # drop the northern row from the catchment

    accumulated = route_release_to_discharge(
        np.ones(N_SMALL_CELLS), south_slope().graph, catchment_mask=mask
    )

    assert accumulated.max() == pytest.approx(float(mask.sum()))


def test_stack_routes_every_timestep():
    stack = np.stack([np.ones(N_SMALL_CELLS), 2.0 * np.ones(N_SMALL_CELLS)])

    accumulated = route_release_to_discharge(stack, south_slope().graph, catchment_mask=all_cells())

    assert accumulated.shape == stack.shape
    assert accumulated.max(axis=1) == pytest.approx([9.0, 18.0])


def test_sinks_receive_everything_released():
    model = south_slope()
    release = np.arange(1.0, N_SMALL_CELLS + 1.0)

    accumulated = route_release_to_discharge(release, model.graph, catchment_mask=all_cells())

    sinks = np.flatnonzero(np.asarray(model.graph.downstream) < 0)
    assert sinks.size
    assert float(accumulated[sinks].sum()) == pytest.approx(release.sum())
    assert float(accumulated.max()) <= release.sum() + 1e-12


def test_pit_does_not_hold_release():
    # A valley sloping to the south edge with a closed pit in its middle.
    rows, cols = np.mgrid[0:7, 0:7]
    top = 10.0 + 2.0 * (6 - rows) + np.abs(cols - 3)
    top[3, 3] = 0.0
    model = structured_model(top.astype(float))
    release = np.ones(49)

    accumulated = route_release_to_discharge(release, model.graph, catchment_mask=all_cells(49))

    pit = 3 * 7 + 3
    assert model.graph.downstream[pit] >= 0
    sinks = np.flatnonzero(np.asarray(model.graph.downstream) < 0)
    assert float(accumulated[sinks].sum()) == pytest.approx(release.sum())
    assert float(accumulated.max()) > float(accumulated[pit])


def test_stream_chd_passes_water_to_outlet():
    # A valley sloping south, its river column held by a stream-role CHD that
    # carries all the release, as the release union counts it.
    n = 11
    rows, cols = np.mgrid[0:n, 0:n]
    top = 50.0 + 2.0 * np.abs(cols - 5) + 1.0 * (n - 1 - rows)
    river = (cols == 5).reshape(-1)
    model = structured_model(top.astype(float), base_level=river)
    release = np.where(river, 1.0, 0.0)

    accumulated = route_release_to_discharge(release, model.graph, catchment_mask=all_cells(n * n))

    outlet = int(np.argmax(accumulated))
    assert model.descent.constant_head[river].all()
    assert float(accumulated[outlet]) == pytest.approx(float(release.sum()))
    assert np.all(model.graph.downstream[river & (np.arange(n * n) != outlet)] >= 0)


def test_outlet_upstream_area_is_catchment_area():
    model = south_slope()

    area = upstream_area(cell_areas(model), model.graph, catchment_mask=all_cells())

    assert isinstance(area, UpstreamArea)
    assert area.m2.max() == pytest.approx(float(cell_areas(model).sum()))


def test_upstream_area_follows_release_graph():
    # The runoff a gauge sees is the runoff over the cells whose release it sees.
    model = south_slope()
    areas = cell_areas(model)

    area = upstream_area(areas, model.graph, catchment_mask=all_cells())
    counts = route_release_to_discharge(
        np.ones(N_SMALL_CELLS), model.graph, catchment_mask=all_cells()
    )

    assert area.m2 == pytest.approx(counts * float(areas[0]))


def test_share_of_a_drained_basin_is_one(caplog):
    model = diagonal_model()

    with caplog.at_level(logging.WARNING):
        area = upstream_area(
            cell_areas(model), model.graph, catchment_mask=all_cells(N_DIAGONAL**2)
        )

    assert area.largest_drainable_share == pytest.approx(1.0)
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


def test_share_matches_direct_computation():
    model = diagonal_model()
    graph = shared_edge_graph(model)
    mask = all_cells(N_DIAGONAL**2)
    areas = cell_areas(model)
    accumulated = route_release_to_discharge(areas, graph, catchment_mask=mask)

    area = upstream_area(areas, graph, catchment_mask=mask)

    assert area.largest_drainable_share == pytest.approx(
        largest_drainable_share(areas, accumulated, mask)
    )
    np.testing.assert_array_equal(area.m2, accumulated)


def test_calls_keep_their_own_share():
    model = diagonal_model()
    areas, mask = cell_areas(model), all_cells(N_DIAGONAL**2)

    drained = upstream_area(areas, model.graph, catchment_mask=mask)
    fragmented = upstream_area(areas, shared_edge_graph(model), catchment_mask=mask)

    assert drained.largest_drainable_share == pytest.approx(1.0)
    assert fragmented.largest_drainable_share < 0.5


def test_catchment_without_area_has_no_share():
    model = south_slope()

    area = upstream_area(np.zeros(N_SMALL_CELLS), model.graph, catchment_mask=all_cells())

    assert area.largest_drainable_share is None


def test_basin_of_d_drains_to_its_area(caplog):
    # With the basin of D as the mask, the largest accumulation is its area.
    model = diagonal_model()
    areas = cell_areas(model)
    talweg_cell = 10 * N_DIAGONAL + 10
    basin = descent_basin(
        model.descent,
        cell_area_m2=areas,
        near=tuple(model.solver_mesh.cell_centers()[talweg_cell]),
    )

    with caplog.at_level(logging.WARNING):
        area = upstream_area(areas, model.graph, catchment_mask=basin.mask)

    assert 0 < int(basin.mask.sum()) < N_DIAGONAL**2
    assert float(np.max(area.m2)) == pytest.approx(basin.area_m2, abs=1e-9)
    assert area.largest_drainable_share == pytest.approx(1.0, abs=1e-12)
    assert not any(record.levelno >= logging.WARNING for record in caplog.records)


# A shared-edge descent cannot follow a talweg that runs diagonally on a square grid,
# so its accumulation fragments instead of reaching the outlet. On a real Nancon run
# the gauge cell drained 0.107 km2 of a 64.631 km2 catchment, two tenths of a per cent.
# Switching the default neighbor rule would change every stream-network calibration,
# so this pins the measurement and leaves the decision open.
NEIGHBOR_RULES = [
    pytest.param(True, 1.0, 1e-9, id="shared nodes drain the valley"),
    pytest.param(False, 0.066, 0.005, id="shared edges strand most of it"),
]


@pytest.mark.parametrize(("diagonal_neighbors", "share", "tol"), NEIGHBOR_RULES)
def test_share_by_neighbor_rule(diagonal_neighbors, share, tol):
    areas, mask, graph = diagonal_valley_on_quads(diagonal_neighbors)

    accumulated = route_release_to_discharge(areas, graph, catchment_mask=mask)

    np.testing.assert_allclose(accumulated.max() / areas.sum(), share, atol=tol)
    np.testing.assert_allclose(largest_drainable_share(areas, accumulated, mask), share, atol=tol)


def test_share_logged_when_graph_cannot_drain(caplog):
    # A share far below one is a disagreement between graph and basin, so the run states it.
    areas, mask, graph = diagonal_valley_on_quads(diagonal_neighbors=False)
    accumulated = route_release_to_discharge(areas, graph, catchment_mask=mask)

    with caplog.at_level(logging.INFO):
        largest_drainable_share(areas, accumulated, mask)

    assert "different drainage" in caplog.text


MASK_REFUSALS = [
    pytest.param(np.zeros(N_SMALL_CELLS, dtype=bool), "holds no cell", id="empty mask"),
    pytest.param(np.ones(4, dtype=bool), "holds 4 cells and the release 9", id="wrong size"),
]


@pytest.mark.parametrize(("mask", "message"), MASK_REFUSALS)
def test_mask_refusals(mask, message):
    with pytest.raises(ValueError, match=message):
        route_release_to_discharge(np.ones(N_SMALL_CELLS), south_slope().graph, catchment_mask=mask)
