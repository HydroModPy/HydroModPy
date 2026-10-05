"""A structure that does not meet the channel tree leaves the ground alone."""

from __future__ import annotations

from shapely.geometry import LineString

from tests._helpers import ground_bench as bench

ROAD_ROW = 10


def test_a_road_that_stops_before_the_channel_is_not_a_crossing() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=2.5)
    short = LineString([(0.0, bench.y_of(ROAD_ROW)), (60.0, bench.y_of(ROAD_ROW))])
    crossings = bench.structures(("road", short))

    out, report = bench.notch(valley, crossings)

    assert (out == valley.dem).all()
    assert report.crossing_points == {}
    assert report.features == {"road": 1}


def test_a_bridge_point_beyond_the_snap_radius_is_skipped_with_its_reason() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=2.5)
    sixty_metres_off = bench.structures(("bridge", bench.bridge_at(bench.AXIS + 6, ROAD_ROW)))

    out, report = bench.notch(valley, sixty_metres_off, snap_radius_m=30.0)

    assert (out == valley.dem).all()
    assert report.skipped == {"off_channel": 1}
    assert report.skipped_detail[0]["kind"] == "bridge"
    assert report.crossing_points == {}


def test_the_same_bridge_point_is_notched_once_the_snap_radius_reaches_it() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=2.5)
    sixty_metres_off = bench.structures(("bridge", bench.bridge_at(bench.AXIS + 6, ROAD_ROW)))

    out, report = bench.notch(valley, sixty_metres_off, snap_radius_m=70.0)

    assert out[ROAD_ROW, bench.AXIS] < valley.dem[ROAD_ROW, bench.AXIS]
    assert report.notched == {"bridge": 1}


def test_a_bridge_point_within_the_radius_snaps_onto_the_channel_and_notches_it() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=2.5)
    crossings = bench.structures(("bridge", bench.bridge_at(bench.AXIS + 2, ROAD_ROW)))

    out, report = bench.notch(valley, crossings, snap_radius_m=30.0)

    assert out[ROAD_ROW, bench.AXIS] == valley.dem[ROAD_ROW, bench.AXIS] - 2.5
    assert report.notched == {"bridge": 1}


def test_a_channel_with_no_pixel_near_the_crossing_is_skipped() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=2.5)
    valley.streams[:, bench.AXIS] = False
    valley.streams[:4, bench.AXIS] = True
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    out, report = bench.notch(valley, crossings)

    assert (out == valley.dem).all()
    assert report.skipped == {"no_channel_pixel": 1}


def test_a_crossing_where_the_ground_is_already_at_the_bed_line_lowers_nothing() -> None:
    valley = bench.build()
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    out, report = bench.notch(valley, crossings)

    assert (out == valley.dem).all()
    assert report.skipped == {"nothing_to_lower": 1}
    assert report.pixels_lowered == 0
