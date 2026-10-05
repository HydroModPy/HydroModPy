"""The notch lowers the embankment on the channel to the bed line, and nothing else."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import LineString

from tests._helpers import ground_bench as bench

ROAD_ROW = 10
HEIGHT = 2.5


def _cut():
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))
    out, report = bench.notch(valley, crossings)
    return valley, out, report


def test_the_embankment_pixel_on_the_channel_falls_to_the_interpolated_bed() -> None:
    valley, out, _ = _cut()

    assert valley.dem[ROAD_ROW, bench.AXIS] == pytest.approx(bench.bed(ROAD_ROW) + HEIGHT)
    assert out[ROAD_ROW, bench.AXIS] == pytest.approx(bench.bed(ROAD_ROW))


def test_nothing_outside_the_notch_moves() -> None:
    valley, out, _ = _cut()

    moved = np.argwhere(out != valley.dem)

    assert moved.tolist() == [[ROAD_ROW, bench.AXIS]]


def test_the_ground_is_never_raised() -> None:
    valley, out, _ = _cut()

    assert (out <= valley.dem).all()


def test_the_report_counts_one_notched_road_and_its_pixels() -> None:
    _, _, report = _cut()

    assert report.crossing_points == {"road": 1}
    assert report.notched == {"road": 1}
    assert report.skipped == {}
    assert report.pixels_lowered == 1
    assert report.max_lowering_m == pytest.approx(HEIGHT)
    assert report.median_lowering_m == pytest.approx(HEIGHT)
    assert report.capped_pixels == 0


def test_a_bed_read_on_both_sides_follows_a_sloping_embankment_foot() -> None:
    """The line joins the two bed levels, so a steeper reach is followed, not levelled."""
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    valley.dem[ROAD_ROW + 3, bench.AXIS] -= 1.0
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    out, _ = bench.notch(valley, crossings)

    z_up = valley.dem[ROAD_ROW - 3, bench.AXIS]
    z_down = valley.dem[ROAD_ROW + 3, bench.AXIS]
    assert out[ROAD_ROW, bench.AXIS] == pytest.approx((z_up + z_down) / 2.0)


def test_a_railway_and_a_bridge_are_cut_like_a_road_and_a_weir_is_left_alone() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    for kind, expected in (("railway", True), ("bridge", True), ("weir", False), ("dam", False)):
        crossings = bench.structures((kind, bench.road_along(ROAD_ROW)))

        out, report = bench.notch(valley, crossings)

        assert bool((out != valley.dem).any()) is expected, kind
        assert (kind in report.notched) is expected, kind


def test_the_kinds_option_leaves_the_other_kinds_alone() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    out, report = bench.notch(valley, crossings, kinds=("railway",))

    assert (out == valley.dem).all()
    assert report.features == {}


def test_two_roads_on_one_channel_are_two_notches() -> None:
    valley = bench.build(embankment_rows=(5, 15), height=HEIGHT)
    crossings = bench.structures(("road", bench.road_along(5)), ("road", bench.road_along(15)))

    out, report = bench.notch(valley, crossings)

    assert out[5, bench.AXIS] == pytest.approx(bench.bed(5))
    assert out[15, bench.AXIS] == pytest.approx(bench.bed(15))
    assert report.notched == {"road": 2}
    assert report.pixels_lowered == 2


def test_a_channel_cut_at_the_crossing_gives_one_crossing_not_one_per_piece() -> None:
    """The extracted vector is cut at its junctions: both pieces touch the road."""
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    x, y = bench.x_of(bench.AXIS), bench.y_of(ROAD_ROW)
    valley.network = gpd.GeoDataFrame(
        geometry=[
            LineString([(x, bench.N * bench.RES - 1.0), (x, y)]),
            LineString([(x, y), (x, 1.0)]),
        ],
        crs=bench.CRS,
    )
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    out, report = bench.notch(valley, crossings)

    assert report.crossing_points == {"road": 1}
    assert report.skipped == {}
    assert out[ROAD_ROW, bench.AXIS] == pytest.approx(bench.bed(ROAD_ROW))
