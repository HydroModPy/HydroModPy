"""largest_drainable_share is returned and kept, not computed and thrown away.

The ratio compares the largest accumulation the routing graph can reach to
the delineated catchment area. It is a property of the graph and the
catchment mask alone, identical from one trial to the next, so
upstream_area_m2 must not compute it and drop it on the floor: this pins that
the value survives the call, that a fragmented graph warns instead of
raising, and that a graph which drains its basin stays silent.

Reuses the diagonal-valley construction of
test_the_discharge_graph_can_go_diagonal: shared edges cannot follow a
talweg running along the grid diagonal, and shared nodes can, so the same
mesh gives one graph that drains its basin and one that does not.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.modflow_common.discharge_routing import (
    largest_drainable_share,
    last_largest_drainable_share,
    route_release_to_discharge,
    routing_graph_for_model,
    upstream_area_m2,
)
from hydromodpy.solver.modflow_grid.solver_mesh import SolverMesh

N = 30


def _diagonal_valley_model() -> SimpleNamespace:
    """A V-shaped valley whose talweg runs along the grid diagonal."""
    rows, cols = np.meshgrid(np.arange(N), np.arange(N), indexing="ij")
    top = 100.0 + 0.5 * np.abs(rows - cols) + 0.01 * (rows + cols)
    botm = np.full((N, N), -10.0, dtype=float)
    mesh = SolverMesh.from_structured_arrays(
        nrow=N,
        ncol=N,
        top=top,
        botm=np.stack([botm]),
    )
    return SimpleNamespace(solver_mesh=mesh)


def _mask() -> np.ndarray:
    return np.ones(N * N, dtype=bool)


def test_a_graph_that_drains_its_basin_keeps_a_ratio_near_one():
    model = _diagonal_valley_model()
    graph = routing_graph_for_model(model, diagonal_neighbors=True)

    upstream_area_m2(model, graph, catchment_mask=_mask())

    assert last_largest_drainable_share() == pytest.approx(1.0)


def test_a_fragmented_graph_keeps_a_ratio_far_from_one():
    model = _diagonal_valley_model()
    graph = routing_graph_for_model(model, diagonal_neighbors=False)

    upstream_area_m2(model, graph, catchment_mask=_mask())

    ratio = last_largest_drainable_share()
    assert ratio is not None
    assert ratio < 0.5


def test_the_kept_ratio_matches_what_the_geometry_actually_computed():
    """upstream_area_m2 must keep the real ratio, not a stand-in value."""
    model = _diagonal_valley_model()
    graph = routing_graph_for_model(model, diagonal_neighbors=False)
    mask = _mask()
    areas = np.asarray(model.solver_mesh.cell_areas(), dtype=float).reshape(-1)
    accumulated = route_release_to_discharge(areas, graph, catchment_mask=mask)
    expected = largest_drainable_share(areas, accumulated, mask)

    upstream_area_m2(model, graph, catchment_mask=mask)

    assert last_largest_drainable_share() == pytest.approx(expected)


def test_a_fragmented_graph_warns_without_refusing(caplog):
    model = _diagonal_valley_model()
    graph = routing_graph_for_model(model, diagonal_neighbors=False)

    with caplog.at_level(logging.WARNING):
        accumulated = upstream_area_m2(model, graph, catchment_mask=_mask())

    assert accumulated is not None
    assert accumulated.shape == (N * N,)
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings
    assert "diagonal_neighbors" in caplog.text


def test_a_graph_that_drains_its_basin_does_not_warn(caplog):
    model = _diagonal_valley_model()
    graph = routing_graph_for_model(model, diagonal_neighbors=True)

    with caplog.at_level(logging.WARNING):
        upstream_area_m2(model, graph, catchment_mask=_mask())

    assert not any(r.levelno >= logging.WARNING for r in caplog.records)
