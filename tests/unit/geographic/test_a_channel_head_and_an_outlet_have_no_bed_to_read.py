"""A crossing needs a reach of channel on each side: a head or an outlet is skipped."""

from __future__ import annotations

import numpy as np

from tests._helpers import ground_bench as bench


def test_a_crossing_at_the_channel_head_is_skipped() -> None:
    valley = bench.build(embankment_rows=(0,), height=2.0)
    crossings = bench.structures(("road", bench.road_along(0)))

    out, report = bench.notch(valley, crossings)

    assert np.array_equal(out, valley.dem)
    assert report.skipped == {"no_upstream_reach": 1}


def test_a_crossing_at_the_outlet_is_skipped() -> None:
    last = bench.N - 1
    valley = bench.build(embankment_rows=(last,), height=2.0)
    crossings = bench.structures(("road", bench.road_along(last)))

    out, report = bench.notch(valley, crossings)

    assert np.array_equal(out, valley.dem)
    assert report.skipped == {"no_downstream_reach": 1}


def test_a_nodata_bed_level_skips_the_crossing() -> None:
    valley = bench.build(embankment_rows=(10,), height=2.0)
    valley.dem[7, bench.AXIS] = -9999.0
    crossings = bench.structures(("road", bench.road_along(10)))

    out, report = bench.notch(valley, crossings)

    assert np.array_equal(out, valley.dem)
    assert report.skipped == {"nodata": 1}


def test_a_reach_shorter_than_the_request_is_read_to_where_the_channel_ends() -> None:
    valley = bench.build(embankment_rows=(2,), height=2.0)
    crossings = bench.structures(("road", bench.road_along(2)))

    out, report = bench.notch(valley, crossings, bed_reach_m=50.0)

    assert report.notched == {"road": 1}
    assert out[2, bench.AXIS] == valley.dem[2, bench.AXIS] - 2.0
