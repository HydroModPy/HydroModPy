"""Upstream of a crossing the walk climbs the branch that drains the larger area."""

from __future__ import annotations

import pytest

from tests._helpers import ground_bench as bench

ROAD_ROW = 14
JUNCTION_ROW = 12
WEST = bench.WEST
TRIBUTARY_BED = 60.0


def _forked(*, tributary_acc: float):
    """The main channel with a tributary from the east joining at the junction row."""
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=2.0)
    for col in range(bench.AXIS + 1, bench.AXIS + 6):
        valley.streams[JUNCTION_ROW, col] = True
        valley.d8[JUNCTION_ROW, col] = WEST
        valley.acc[JUNCTION_ROW, col] = tributary_acc
        valley.dem[JUNCTION_ROW, col] = TRIBUTARY_BED
    # The main branch above the junction, kept low so the two reads differ.
    valley.acc[JUNCTION_ROW - 1, bench.AXIS] = 2.0
    return valley


def test_the_larger_tributary_gives_the_upstream_bed_level() -> None:
    valley = _forked(tributary_acc=50.0)
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    out, _ = bench.notch(valley, crossings, bed_reach_m=40.0, max_depth_m=30.0)

    # 13 (10 m), the junction row (20 m), then east along the tributary: 30 m and 40 m.
    z_down = bench.bed(ROAD_ROW + 4)
    expected = TRIBUTARY_BED + (z_down - TRIBUTARY_BED) * 40.0 / 80.0
    assert out[ROAD_ROW, bench.AXIS] == pytest.approx(expected)


def test_the_main_branch_wins_when_it_drains_more() -> None:
    valley = _forked(tributary_acc=1.0)
    valley.acc[JUNCTION_ROW - 1, bench.AXIS] = 11.0
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    out, _ = bench.notch(valley, crossings, bed_reach_m=40.0, max_depth_m=30.0)

    assert out[ROAD_ROW, bench.AXIS] == pytest.approx(bench.bed(ROAD_ROW))


def test_the_tributary_pixels_are_never_lowered_by_the_main_notch() -> None:
    valley = _forked(tributary_acc=50.0)
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    out, _ = bench.notch(valley, crossings, bed_reach_m=40.0, max_depth_m=30.0)

    assert (out[JUNCTION_ROW, bench.AXIS + 1 :] == valley.dem[JUNCTION_ROW, bench.AXIS + 1 :]).all()
