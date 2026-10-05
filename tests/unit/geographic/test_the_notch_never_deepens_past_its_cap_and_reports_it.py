"""max_depth bounds the lowering of any pixel, and a pixel it bounds is reported."""

from __future__ import annotations

import pytest

from tests._helpers import ground_bench as bench

ROAD_ROW = 10


def test_a_pixel_is_lowered_by_the_cap_when_the_embankment_is_higher() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=6.0)
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    out, report = bench.notch(valley, crossings, max_depth_m=3.0)

    assert valley.dem[ROAD_ROW, bench.AXIS] - out[ROAD_ROW, bench.AXIS] == pytest.approx(3.0)
    assert report.max_lowering_m == pytest.approx(3.0)
    assert report.capped_pixels == 1


def test_a_pixel_lowered_exactly_to_the_cap_by_the_line_is_not_reported_capped() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=3.0)
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    _, report = bench.notch(valley, crossings, max_depth_m=3.0)

    assert report.capped_pixels == 0


def test_a_cap_larger_than_the_embankment_never_bites() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=6.0)
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    out, report = bench.notch(valley, crossings, max_depth_m=10.0)

    assert out[ROAD_ROW, bench.AXIS] == pytest.approx(bench.bed(ROAD_ROW))
    assert report.capped_pixels == 0


def test_two_notches_over_one_pixel_never_exceed_the_cap_together() -> None:
    """A road and a bridge at the same crossing lower the pixel once, to the cap at most."""
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=6.0)
    crossings = bench.structures(
        ("road", bench.road_along(ROAD_ROW)),
        ("bridge", bench.bridge_at(bench.AXIS, ROAD_ROW)),
    )

    out, _ = bench.notch(valley, crossings, max_depth_m=3.0)

    assert valley.dem[ROAD_ROW, bench.AXIS] - out[ROAD_ROW, bench.AXIS] == pytest.approx(3.0)
