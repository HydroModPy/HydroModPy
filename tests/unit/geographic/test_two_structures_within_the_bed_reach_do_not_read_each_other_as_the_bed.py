"""The bed ends of a crossing are read beyond the embankments of its neighbours."""

from __future__ import annotations

import pytest

from hydromodpy.spatial.geographic.core import ground_corrections
from tests._helpers import ground_bench as bench

HEIGHT = 2.5


def _two_embankments(rows: tuple[int, int], **options):
    valley = bench.build(embankment_rows=rows, height=HEIGHT)
    crossings = bench.structures(
        ("road", bench.road_along(rows[0])), ("railway", bench.road_along(rows[1]))
    )
    return valley, *bench.notch(valley, crossings, **options)


def test_two_embankments_thirty_metres_apart_are_both_cut_to_their_own_bed() -> None:
    rows = (8, 11)

    _, out, report = _two_embankments(rows)

    for row in rows:
        assert out[row, bench.AXIS] == pytest.approx(bench.bed(row))
    assert report.notched == {"road": 1, "railway": 1}
    assert report.skipped == {}
    assert report.pixels_lowered == 2


def test_the_ground_between_the_two_embankments_is_not_touched() -> None:
    valley, out, _ = _two_embankments((8, 11))

    assert (out[9:11, :] == valley.dem[9:11, :]).all()


def test_neighbours_one_cell_apart_are_cut_the_same_way() -> None:
    rows = (9, 10)

    _, out, _ = _two_embankments(rows)

    for row in rows:
        assert out[row, bench.AXIS] == pytest.approx(bench.bed(row))


def test_a_wide_reach_reads_over_the_neighbour_as_before() -> None:
    """With the reach far beyond both, nothing needs moving and the line is the same."""
    rows = (8, 12)

    _, out, _ = _two_embankments(rows, bed_reach_m=60.0)

    for row in rows:
        assert out[row, bench.AXIS] == pytest.approx(bench.bed(row))


def test_spans_that_do_not_settle_are_skipped_and_reported_not_cut_against_a_wall(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ground_corrections, "_MAX_PLAN_PASSES", 1)

    valley, out, report = _two_embankments((8, 11))

    assert (out == valley.dem).all()
    assert report.skipped == {"no_bed_end": 2}
