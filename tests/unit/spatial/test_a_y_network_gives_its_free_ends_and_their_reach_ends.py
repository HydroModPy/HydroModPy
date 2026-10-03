"""The free ends of a mapped network are found geometrically, with their reach ends.

A Y network has three free ends: two heads and the outlet end. Which of them
is upstream is decided later, on the criterion graph; here each free end only
carries the other end of the merged reach it closes, the junction.
"""

from __future__ import annotations

import numpy as np
import pytest

from hydromodpy.spatial.mesh.ops.network_heads import network_head_candidates

shapely = pytest.importorskip("shapely")

from shapely.geometry import LineString  # noqa: E402

CRS = "EPSG:2154"


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
