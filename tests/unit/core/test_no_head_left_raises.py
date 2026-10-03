"""A map that keeps no head draws nothing, and the criterion says why."""

from __future__ import annotations

import pytest

from tests.unit.core._heads_valley import AXIS, N_ROWS, candidates, centre, valley_geometry


def test_every_head_lost_raises_naming_the_radius_and_the_area() -> None:
    heads = candidates([((-200.0, 155.0), centre(15, AXIS))])

    with pytest.raises(ValueError, match=r"snap radius 100 m.*0\.02 km2"):
        valley_geometry(heads, min_drained_area_m2=2.0e4)


def test_a_map_with_only_a_downstream_end_raises() -> None:
    heads = candidates([(centre(N_ROWS - 1, AXIS), centre(5, AXIS))])

    with pytest.raises(ValueError, match="1 free end"):
        valley_geometry(heads)


def test_the_geometry_takes_exactly_one_map() -> None:
    from hydromodpy.core.stream_geometry import build_network_geometry

    with pytest.raises(ValueError, match="exactly one"):
        build_network_geometry(
            topography=[1.0],
            face_node_connectivity=[[0, 1, 2, 3]],
            vertices=[[0, 0], [1, 0], [1, 1], [0, 1]],
            cell_area_m2=[1.0],
            mean_recharge_m_s=0.0,
            tau_specific_ratio=0.0,
        )
