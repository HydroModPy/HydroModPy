"""The free ends of a mapped network are found geometrically, with their reach ends.

Each free end carries the other end of the merged reach it closes; which one is upstream is decided
later, on the criterion graph. Lines that touch without a shared vertex are noded, and a ring or a
loop has no free end: the point where a reach meets a pond outline is a junction, never a head.
"""

import logging

import numpy as np
import pytest
from pyproj import Transformer
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


def test_sampling_step() -> None:
    lines = [LineString([(0.0, 0.0), (0.0, 100.0)])]
    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS, sample_step_m=10.0)
    np.testing.assert_allclose(candidates.map_points_xy[:, 1], np.arange(0.0, 101.0, 10.0))


def test_t_junction_is_noded() -> None:
    lines = [LineString([(0.0, 0.0), (100.0, 0.0)]), LineString([(50.0, 80.0), (50.0, 0.0)])]
    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS)
    heads = sorted(tuple(map(float, head)) for head in candidates.head_xy)
    assert heads == [(0.0, 0.0), (50.0, 80.0), (100.0, 0.0)]
    assert {tuple(map(float, end)) for end in candidates.reach_end_xy} == {(50.0, 0.0)}


OUTLINE = Polygon([(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)])


def test_free_end_on_the_cut_outline() -> None:
    lines = [LineString([(50.0, 50.0), (100.0, 50.0)])]
    candidates = network_head_candidates(
        lines, mesh_crs=CRS, geometry_crs=CRS, cut_outline=OUTLINE, cut_crs=CRS
    )

    assert _sorted_pairs(candidates) == [((50.0, 50.0), (100.0, 50.0))]
    assert candidates.n_cut_ends == 1


def test_cut_outline_in_degrees() -> None:
    # The outline is a Lambert-93 square given in lon/lat. Its corner is the end of the line.
    corners = [(350_000.0, 6_790_000.0), (350_100.0, 6_790_000.0), (350_100.0, 6_790_100.0)]
    to_degrees = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    outline = Polygon([to_degrees.transform(x, y) for x, y in [*corners, (350_000.0, 6_790_100.0)]])
    lines = [LineString([(350_050.0, 6_790_050.0), (350_100.0, 6_790_100.0)])]

    candidates = network_head_candidates(
        lines, mesh_crs=CRS, geometry_crs=CRS, cut_outline=outline, cut_crs="EPSG:4326"
    )

    assert _sorted_pairs(candidates) == [((350_050.0, 6_790_050.0), (350_100.0, 6_790_100.0))]
    assert candidates.n_cut_ends == 1


@pytest.mark.parametrize(
    ("outlet", "message"),
    [
        (None, "1 reach(es)"),
        ((-90.0, 50.0), "1 reach(es)"),
        ((5000.0, 50.0), "1 reach(es)"),
    ],
    ids=["no outlet", "outlet at one end", "outlet far away"],
)
def test_reach_cut_at_both_ends_warns(caplog, outlet, message) -> None:
    # Both ends of the only reach lie on the outline: nothing traces it, and it counts once.
    lines = [LineString([(0.0, 50.0), (100.0, 50.0)])]
    with caplog.at_level(logging.WARNING):
        candidates = network_head_candidates(
            lines,
            mesh_crs=CRS,
            geometry_crs=CRS,
            cut_outline=OUTLINE,
            cut_crs=CRS,
            outlet_xy=outlet,
        )

    assert candidates.head_xy.shape == (0, 2)
    assert candidates.n_cut_ends == 2
    (warning,) = [r.getMessage() for r in caplog.records if "no free end" in r.getMessage()]
    assert warning.startswith(message)


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
def test_ring_and_loop_free_ends(lines, heads) -> None:
    candidates = network_head_candidates(lines, mesh_crs=CRS, geometry_crs=CRS)
    np.testing.assert_allclose(candidates.head_xy, heads)


def test_empty_map() -> None:
    candidates = network_head_candidates([LineString()], mesh_crs=CRS, geometry_crs=CRS)
    assert candidates.n_candidates == 0
    assert candidates.map_points_xy.shape == (0, 2)


@pytest.mark.parametrize("step", [0.0, -10.0, float("nan")])
def test_refused_step(step: float) -> None:
    with pytest.raises(ValueError, match="sample_step_m must be positive"):
        network_head_candidates(
            [LineString([(0, 0), (1, 0)])], mesh_crs=CRS, geometry_crs=CRS, sample_step_m=step
        )


def test_refused_geometry() -> None:
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
def test_refused_shapes(fields, message) -> None:
    base = {
        "head_xy": np.zeros((1, 2)),
        "reach_end_xy": np.zeros((1, 2)),
        "map_points_xy": np.zeros((0, 2)),
    }
    with pytest.raises(ValueError, match=message):
        HeadCandidates(**{**base, **fields})
