"""The free ends of a mapped network are found geometrically, with their reach ends.

Each free end carries the other end of the merged reach it closes; which one is upstream is decided
later, on the criterion graph. Lines that touch without a shared vertex are noded, and a ring or a
loop has no free end: the point where a reach meets a pond outline is a junction, never a head.
"""

import numpy as np
import pytest
from shapely.geometry import (
    GeometryCollection,
    LinearRing,
    LineString,
    MultiLineString,
    Point,
    Polygon,
)

from hydromodpy.spatial.geographic.core.network_heads import line_parts, network_head_candidates
from tests._helpers.mesh_cases import LAMBERT93_WKT

CRS = LAMBERT93_WKT


def _sorted_pairs(candidates) -> list[tuple[tuple[float, float], tuple[float, float]]]:
    return sorted(
        (tuple(map(float, head)), tuple(map(float, end)))
        for head, end in zip(candidates.head_xy, candidates.reach_end_xy, strict=True)
    )


@pytest.mark.parametrize(
    ("lines", "pairs"),
    [
        (
            [
                LineString([(0.0, 0.0), (50.0, 50.0)]),
                LineString([(100.0, 0.0), (50.0, 50.0)]),
                LineString([(50.0, 50.0), (50.0, 150.0)]),
            ],
            [
                ((0.0, 0.0), (50.0, 50.0)),
                ((50.0, 150.0), (50.0, 50.0)),
                ((100.0, 0.0), (50.0, 50.0)),
            ],
        ),
        (
            [LineString([(0.0, 0.0), (0.0, 40.0)]), LineString([(0.0, 40.0), (0.0, 100.0)])],
            [((0.0, 0.0), (0.0, 100.0)), ((0.0, 100.0), (0.0, 0.0))],
        ),
    ],
    ids=["a y network gives two heads and the outlet end", "a split reach is merged first"],
)
def test_each_free_end_carries_the_other_end_of_its_merged_reach(lines, pairs) -> None:
    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS)
    assert _sorted_pairs(candidates) == pairs


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

    def test_without_the_outline_every_free_end_is_a_candidate(self) -> None:
        lines = [LineString([(50.0, 50.0), (100.0, 50.0)])]
        candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS)

        assert candidates.n_candidates == 2
        assert candidates.n_cut_ends == 0

    def test_an_end_a_metre_inside_the_outline_is_a_head(self) -> None:
        lines = [LineString([(50.0, 50.0), (99.0, 50.0)])]
        candidates = network_head_candidates(
            lines, mesh_crs=CRS, geometry_crs=CRS, cut_outline=self.OUTLINE, cut_crs=CRS
        )

        assert candidates.n_candidates == 2


def test_the_lines_are_reprojected_to_the_mesh_crs() -> None:
    lines = [LineString([(-1.6, 48.1), (-1.6, 48.11)])]
    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs="EPSG:4326")
    assert candidates.n_candidates == 2
    assert candidates.head_xy[:, 0].min() > 1.0e5


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


def test_nested_collections_give_their_lines_and_a_point_length_line_is_left_out() -> None:
    first = LineString([(0.0, 0.0), (10.0, 0.0)])
    second = LineString([(0.0, 5.0), (10.0, 5.0)])
    ring = LinearRing([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)])
    nested = GeometryCollection([MultiLineString([first, second]), LineString([(3, 3), (3, 3)])])
    parts = line_parts([nested, ring, LineString()])
    assert [part.wkt for part in parts] == [first.wkt, second.wkt, ring.wkt]


def test_a_point_layer_is_not_a_network_and_an_areal_feature_not_a_line() -> None:
    with pytest.raises(ValueError, match="rasterizes lines; got a Point"):
        network_head_candidates([Point(0.0, 0.0)], mesh_crs=CRS, geometry_crs=CRS)
    with pytest.raises(ValueError, match="rasterizes lines; got a Polygon"):
        line_parts([Point(0.0, 0.0).buffer(5.0)])
