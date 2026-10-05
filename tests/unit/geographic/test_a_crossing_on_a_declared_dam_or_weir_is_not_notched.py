"""A road on a dam crest is the dam, not a wall: a declared dam, weir or lake stops the notch."""

from __future__ import annotations

import numpy as np
import pytest
from shapely.geometry import LineString, box

from tests._helpers import ground_bench as bench

DAM_ROW = 10
POND_LEVEL = 95.0
CREST = 100.0


def _pond_behind_a_dam():
    """A flat pond on rows 3 to 9, a dam crest on row 10, the channel below it."""
    valley = bench.build()
    valley.dem[3:DAM_ROW, :] = np.minimum(valley.dem[3:DAM_ROW, :], POND_LEVEL)
    valley.dem[3:DAM_ROW, bench.AXIS] = POND_LEVEL
    valley.dem[DAM_ROW, :] = CREST
    return valley


def test_a_road_on_a_dam_declared_in_the_same_file_is_left_alone() -> None:
    valley = _pond_behind_a_dam()
    crossings = bench.structures(
        ("road", bench.road_along(DAM_ROW)), ("dam", bench.bridge_at(bench.AXIS, DAM_ROW))
    )

    out, report = bench.notch(valley, crossings)

    assert np.array_equal(out, valley.dem)
    assert report.notched == {}
    assert report.skipped == {"dam_or_weir": 1}
    assert report.crossing_points == {"road": 1}
    assert report.capped_pixels == 0


def test_a_weir_within_the_snap_radius_of_the_crossing_stops_it_too() -> None:
    valley = bench.build(embankment_rows=(DAM_ROW,), height=2.5)
    crossings = bench.structures(
        ("road", bench.road_along(DAM_ROW)), ("weir", bench.bridge_at(bench.AXIS + 2, DAM_ROW))
    )

    out, report = bench.notch(valley, crossings, snap_radius_m=30.0)

    assert np.array_equal(out, valley.dem)
    assert report.skipped == {"dam_or_weir": 1}


def test_a_dam_farther_than_the_snap_radius_leaves_the_notch_on() -> None:
    valley = bench.build(embankment_rows=(DAM_ROW,), height=2.5)
    crossings = bench.structures(
        ("road", bench.road_along(DAM_ROW)), ("dam", bench.bridge_at(bench.AXIS + 5, DAM_ROW))
    )

    out, report = bench.notch(valley, crossings, snap_radius_m=30.0)

    assert out[DAM_ROW, bench.AXIS] == pytest.approx(bench.bed(DAM_ROW))
    assert report.notched == {"road": 1}


def test_a_dam_or_weir_is_a_barrier_even_when_it_is_not_among_the_kinds_to_notch() -> None:
    valley = _pond_behind_a_dam()
    crossings = bench.structures(
        ("road", bench.road_along(DAM_ROW)), ("dam", bench.bridge_at(bench.AXIS, DAM_ROW))
    )

    out, _ = bench.notch(valley, crossings, kinds=("road",))

    assert np.array_equal(out, valley.dem)


def test_a_dam_carve_line_at_the_crossing_stops_the_notch() -> None:
    valley = _pond_behind_a_dam()
    crossings = bench.structures(("road", bench.road_along(DAM_ROW)))
    line = LineString([(bench.x_of(bench.AXIS - 3), bench.y_of(DAM_ROW)), (bench.x_of(7), 95.0)])

    out, report = bench.notch(valley, crossings, dam_lines=[line])

    assert np.array_equal(out, valley.dem)
    assert report.skipped == {"dam_or_weir": 1}


def test_a_crossing_whose_chain_touches_a_declared_lake_is_left_alone() -> None:
    valley = _pond_behind_a_dam()
    crossings = bench.structures(("road", bench.road_along(DAM_ROW)))
    pond = box(
        bench.x_of(bench.AXIS - 4),
        bench.y_of(DAM_ROW - 1),
        bench.x_of(bench.AXIS + 4),
        bench.y_of(5),
    )

    out, report = bench.notch(valley, crossings, lakes=[pond])

    assert np.array_equal(out, valley.dem)
    assert report.skipped == {"dam_or_weir": 1}


def test_a_lake_away_from_the_chain_changes_nothing() -> None:
    valley = bench.build(embankment_rows=(DAM_ROW,), height=2.5)
    crossings = bench.structures(("road", bench.road_along(DAM_ROW)))
    far = box(0.0, 0.0, 30.0, 30.0)

    out, report = bench.notch(valley, crossings, lakes=[far])

    assert out[DAM_ROW, bench.AXIS] == pytest.approx(bench.bed(DAM_ROW))
    assert report.notched == {"road": 1}


def test_the_skip_is_in_the_report_with_its_meaning() -> None:
    valley = _pond_behind_a_dam()
    crossings = bench.structures(
        ("road", bench.road_along(DAM_ROW)), ("dam", bench.bridge_at(bench.AXIS, DAM_ROW))
    )

    _, report = bench.notch(valley, crossings)

    detail = report.skipped_detail[0]
    assert detail["reason"] == "dam_or_weir"
    assert detail["kind"] == "road"
    assert "dam" in detail["meaning"]
