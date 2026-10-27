"""The free ends of a mapped network are found geometrically, with their reach ends.

A Y network has three free ends: two heads and the outlet end. Which of them
is upstream is decided later, on the criterion graph; here each free end only
carries the other end of the merged reach it closes, the junction.

Mapped lines often touch without sharing a vertex: a tributary ending on the
inside of a reach still meets it once the lines are noded. A pond outline drawn
as a ring, or a line that loops back on itself, has no free end, and the point
where a reach meets it is a junction: counted once, it would be read as a head
and start a stream at the pond.
"""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, Point

from hydromodpy.spatial.mesh.ops.network_heads import network_head_candidates
from tests._helpers.mesh_cases import LAMBERT93_WKT

CRS = LAMBERT93_WKT


def _sorted_pairs(candidates) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return sorted(
        (tuple(map(float, head)), tuple(map(float, end)))
        for head, end in zip(candidates.head_xy, candidates.reach_end_xy, strict=True)
    )


def test_a_y_network_gives_two_heads_and_the_outlet_end() -> None:
    lines = [
        LineString([(0.0, 0.0), (50.0, 50.0)]),
        LineString([(100.0, 0.0), (50.0, 50.0)]),
        LineString([(50.0, 50.0), (50.0, 150.0)]),
    ]

    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS)

    assert _sorted_pairs(candidates) == [
        ((0.0, 0.0), (50.0, 50.0)),
        ((50.0, 150.0), (50.0, 50.0)),
        ((100.0, 0.0), (50.0, 50.0)),
    ]


def test_a_reach_split_in_two_lines_is_merged_before_its_ends_are_read() -> None:
    lines = [
        LineString([(0.0, 0.0), (0.0, 40.0)]),
        LineString([(0.0, 40.0), (0.0, 100.0)]),
    ]

    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS)

    assert _sorted_pairs(candidates) == [
        ((0.0, 0.0), (0.0, 100.0)),
        ((0.0, 100.0), (0.0, 0.0)),
    ]


def test_the_map_is_sampled_every_step_along_its_lines() -> None:
    lines = [LineString([(0.0, 0.0), (0.0, 100.0)])]

    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS, sample_step_m=10.0)

    np.testing.assert_allclose(candidates.map_points_xy[:, 1], np.arange(0.0, 101.0, 10.0))


def test_a_t_junction_without_a_shared_vertex_is_noded() -> None:
    lines = [
        LineString([(0.0, 0.0), (100.0, 0.0)]),
        LineString([(50.0, 80.0), (50.0, 0.0)]),
    ]

    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS)

    heads = sorted(tuple(map(float, head)) for head in candidates.head_xy)
    assert heads == [(0.0, 0.0), (50.0, 80.0), (100.0, 0.0)]
    assert {tuple(map(float, end)) for end in candidates.reach_end_xy} == {(50.0, 0.0)}


def test_the_lines_are_reprojected_to_the_mesh_crs() -> None:
    lines = [LineString([(-1.6, 48.1), (-1.6, 48.11)])]

    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs="EPSG:4326")

    assert candidates.n_candidates == 2
    assert candidates.head_xy[:, 0].min() > 1.0e5


def test_a_reach_meeting_a_ring_ends_at_a_junction() -> None:
    pond = LineString([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)])
    outflow = LineString([(0, 0), (-50, -50)])

    candidates = network_head_candidates([pond, outflow], mesh_crs=CRS, geometry_crs=CRS)

    np.testing.assert_allclose(candidates.head_xy, [[-50.0, -50.0]])


def test_a_line_looping_back_on_itself_has_one_free_end() -> None:
    lollipop = LineString([(0, 0), (100, 0), (100, 50), (50, 50), (50, 0)])

    candidates = network_head_candidates([lollipop], mesh_crs=CRS, geometry_crs=CRS)

    np.testing.assert_allclose(candidates.head_xy, [[0.0, 0.0]])


def test_a_map_without_a_line_has_no_candidate() -> None:
    candidates = network_head_candidates([LineString()], mesh_crs=CRS, geometry_crs=CRS)

    assert candidates.n_candidates == 0
    assert candidates.map_points_xy.shape == (0, 2)


@pytest.mark.parametrize("step", [0.0, -10.0, float("nan")])
def test_a_sampling_step_that_is_not_positive_is_refused(step: float) -> None:
    with pytest.raises(ValueError, match="sample_step_m must be positive"):
        network_head_candidates(
            [LineString([(0, 0), (1, 0)])], mesh_crs=CRS, geometry_crs=CRS, sample_step_m=step
        )


def test_a_point_layer_is_not_a_network() -> None:
    with pytest.raises(ValueError, match="rasterizes lines; got a Point"):
        network_head_candidates([Point(0.0, 0.0)], mesh_crs=CRS, geometry_crs=CRS)
