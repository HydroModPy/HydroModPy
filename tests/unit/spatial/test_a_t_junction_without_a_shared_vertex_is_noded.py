"""A tributary ending on the inside of a reach still meets it.

Mapped lines often touch without sharing a vertex. Unnoded, the main reach
would keep its two ends as each other's reach end and the junction would not
exist; noded, every free end closes on the junction.
"""

from __future__ import annotations

import pytest

from hydromodpy.spatial.mesh.ops.network_heads import network_head_candidates

shapely = pytest.importorskip("shapely")

from shapely.geometry import LineString  # noqa: E402

CRS = "EPSG:2154"


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
