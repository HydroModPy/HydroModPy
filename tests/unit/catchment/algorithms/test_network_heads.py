"""The free ends of a mapped network are found geometrically, with their reach ends.

Each free end carries the other end of the merged reach it closes; which one is upstream is decided
later, on the criterion graph. Lines that touch without a shared vertex are noded, and a ring or a
loop has no free end: the point where a reach meets a pond outline is a junction, never a head.
"""

import numpy as np
import pytest
from shapely.geometry import LineString, Point, Polygon

from hydromodpy.catchment.algorithms.network_heads import (
    HeadCandidates,
    line_parts,
    network_head_candidates,
)
from tests._helpers.mesh_cases import LAMBERT93_WKT

CRS = LAMBERT93_WKT


def _sorted_pairs(candidates) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return sorted(
        (tuple(map(float, head)), tuple(map(float, end)))
        for head, end in zip(candidates.head_xy, candidates.reach_end_xy, strict=True)
    )


def test_the_map_is_sampled_every_step_along_its_lines() -> None:
    lines = [LineString([(0.0, 0.0), (0.0, 100.0)])]
    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS, sample_step_m=10.0)
    np.testing.assert_allclose(candidates.map_points_xy[:, 1], np.arange(0.0, 101.0, 10.0))


def test_a_t_junction_without_a_shared_vertex_is_noded() -> None:
    lines = [LineString([(0.0, 0.0), (100.0, 0.0)]), LineString([(50.0, 80.0), (50.0, 0.0)])]
    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS)
    heads = sorted(tuple(map(float, head)) for head in candidates.head_xy)
    assert heads == [(0.0, 0.0), (50.0, 80.0), (100.0, 0.0)]
    assert {tuple(map(float, end)) for end in candidates.reach_end_xy} == {(50.0, 0.0)}


class TestAnEndOfTheCutIsNoHead:
    OUTLINE = Polygon([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)])

    def test_a_free_end_on_the_outline_is_left_out_and_counted(self) -> None:
        lines = [LineString([(50.0, 50.0), (100.0, 50.0)])]
        candidates = network_head_candidates(
            lines, mesh_crs=CRS, geometry_crs=CRS, cut_outline=self.OUTLINE, cut_crs=CRS
        )

        assert _sorted_pairs(candidates) == [((50.0, 50.0), (100.0, 50.0))]
        assert candidates.n_cut_ends == 1


@pytest.mark.parametrize(
    ("lines", "heads"),
    [
        (
            [
                LineString([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]),
                LineString([(0, 0), (-50, -50)]),
            ],
            [[-50.0, -50.0]],
        ),
        ([LineString([(0, 0), (100, 0), (100, 50), (50, 50), (50, 0)])], [[0.0, 0.0]]),
    ],
    ids=["a reach meeting a ring ends at a junction", "a lollipop has one free end"],
)
def test_a_ring_or_a_loop_has_no_free_end(lines, heads) -> None:
    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS)
    np.testing.assert_allclose(candidates.head_xy, heads)


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


def test_a_point_layer_is_not_a_network_and_an_areal_feature_not_a_line() -> None:
    with pytest.raises(ValueError, match="rasterizes lines; got a Point"):
        network_head_candidates([Point(0.0, 0.0)], mesh_crs=CRS, geometry_crs=CRS)
    with pytest.raises(ValueError, match="rasterizes lines; got a Polygon"):
        line_parts([Point(0.0, 0.0).buffer(5.0)])


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (
            {"head_xy": np.zeros((2, 3)), "reach_end_xy": np.zeros((2, 3))},
            "head_xy must have shape",
        ),
        ({"head_xy": np.zeros((2, 2)), "reach_end_xy": np.zeros((1, 2))}, "pair row for row"),
        ({"forced_cells": np.zeros((2, 2), dtype=int)}, "forced_cells must be 1-D"),
    ],
    ids=["points_not_pairs", "ends_not_paired", "forced_cells_not_a_list"],
)
def test_head_candidates_refuse_a_shape_that_does_not_pair(fields, message) -> None:
    base = {
        "head_xy": np.zeros((1, 2)),
        "reach_end_xy": np.zeros((1, 2)),
        "map_points_xy": np.zeros((0, 2)),
    }
    with pytest.raises(ValueError, match=message):
        HeadCandidates(**{**base, **fields})
