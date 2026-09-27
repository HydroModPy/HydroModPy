"""The stream criterion descends D8 by default, as the paper does.

Abherve et al. (2023) trace their distances with WhiteboxTools on a D8
pointer. The default is one object, ``STREAM_CRITERION_DEFAULTS``, and every
place that rebuilds the criterion reads it: a figure drawn on another graph
than the trial scored shows a partition the numbers were never computed on.
"""

from __future__ import annotations

import inspect
import math

import numpy as np
import pytest

from hydromodpy.calibration.config import CalibOutputNetwork
from hydromodpy.core.stream_criterion_defaults import STREAM_CRITERION_DEFAULTS
from hydromodpy.core.stream_geometry import build_network_geometry
from hydromodpy.core.stream_network import build_simulated_network
from hydromodpy.core.topographic_distance import build_downslope_metric
from hydromodpy.display.figures._routing_surface import routing_surface_from_run
from hydromodpy.display.figures.depression_map import DepressionMap
from hydromodpy.display.figures.flow_direction_map import FlowDirectionMap
from hydromodpy.results.derive.stream_network import network_comparison_from_run
from tests._helpers.ugrid_meshes import quad_mesh

SIZE = 6
CELL = 10.0


def _default(function) -> object:
    return inspect.signature(function).parameters["diagonal_neighbors"].default


def test_the_shared_default_is_the_paper_s_d8() -> None:
    assert STREAM_CRITERION_DEFAULTS.diagonal_neighbors is True
    assert CalibOutputNetwork.model_fields["diagonal_neighbors"].default is True


@pytest.mark.parametrize(
    "function",
    [
        build_network_geometry,
        build_downslope_metric,
        network_comparison_from_run,
        routing_surface_from_run,
        FlowDirectionMap.render,
        DepressionMap.render,
    ],
    ids=lambda function: function.__qualname__,
)
def test_every_rebuild_reads_the_same_default(function) -> None:
    assert _default(function) is STREAM_CRITERION_DEFAULTS.diagonal_neighbors


def _diagonal_plane() -> np.ndarray:
    """A surface dropping one metre east and one south, to the south-east corner."""
    rows = np.arange(SIZE, dtype=float)[:, None]
    cols = np.arange(SIZE, dtype=float)[None, :]
    return (100.0 - rows - cols).reshape(-1)


def _geometry(topography, connectivity, vertices, **overrides):
    n_cells = topography.size
    observed = np.zeros(n_cells, dtype=bool)
    observed[-1] = True
    return build_network_geometry(
        topography=topography,
        face_node_connectivity=connectivity,
        vertices=vertices,
        observed=observed,
        cell_area_m2=np.full(n_cells, CELL * CELL),
        mean_recharge_m_s=1e-8,
        tau_specific_ratio=0.0,
        delineated_catchment=np.ones(n_cells, dtype=bool),
        **overrides,
    )


def test_the_flood_the_graph_and_the_cap_walk_the_same_eight_neighbours() -> None:
    vertices, connectivity = quad_mesh(SIZE, SIZE, cell_size=CELL)

    geometry = _geometry(_diagonal_plane(), connectivity, vertices)

    assert geometry.metric.diagonal_neighbors is True
    # Every cell reaches the sealed outlet after the flood: it was fed the
    # graph the metric descends.
    assert np.all(np.isfinite(geometry.distance_to_observed[geometry.catchment]))
    # A diagonal step is sqrt(2) cells long, centroid to centroid, so the
    # longest descent is the diagonal of the square and not its two sides.
    assert geometry.saturation_cap_m == pytest.approx(math.sqrt(2.0) * CELL * (SIZE - 1))


def test_d4_is_still_there_when_asked_for() -> None:
    vertices, connectivity = quad_mesh(SIZE, SIZE, cell_size=CELL)

    geometry = _geometry(_diagonal_plane(), connectivity, vertices, diagonal_neighbors=False)

    assert geometry.metric.diagonal_neighbors is False
    assert geometry.saturation_cap_m == pytest.approx(2.0 * CELL * (SIZE - 1))


def test_the_simulated_network_closes_downslope_over_the_diagonal() -> None:
    vertices, connectivity = quad_mesh(SIZE, SIZE, cell_size=CELL)
    geometry = _geometry(_diagonal_plane(), connectivity, vertices)
    release = np.zeros(SIZE * SIZE)
    release[0] = 1.0  # the highest corner

    network = build_simulated_network(
        release, threshold_m3_s=geometry.threshold_m3_s, metric=geometry.metric
    ).network

    diagonal = [row * SIZE + row for row in range(SIZE)]
    assert sorted(np.flatnonzero(network).tolist()) == diagonal


def _triangulated(nrow: int, ncol: int) -> tuple[np.ndarray, np.ndarray]:
    """Split every quad of a grid into two triangles."""
    vertices, quads = quad_mesh(nrow, ncol, cell_size=CELL)
    triangles = []
    for a, b, c, d in np.asarray(quads)[:, :4]:
        triangles.append([a, b, c])
        triangles.append([a, c, d])
    return vertices, np.asarray(triangles, dtype=int)


def test_a_mesh_without_quadrilaterals_is_scored_on_shared_edges_without_failing() -> None:
    vertices, triangles = _triangulated(4, 4)
    centres = np.asarray(vertices, dtype=float)[triangles][:, :, :2].mean(axis=1)
    topography = 100.0 - centres[:, 0] / CELL - centres[:, 1] / CELL

    geometry = _geometry(topography, triangles, vertices)

    assert geometry.metric.diagonal_neighbors is False
    assert np.all(np.isfinite(geometry.distance_to_observed[geometry.catchment]))
