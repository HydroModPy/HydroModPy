"""notch_width widens the cut across the channel, and only where the line is below the ground."""

from __future__ import annotations

import numpy as np
import pytest

from tests._helpers import ground_bench as bench

ROAD_ROW = 10
HEIGHT = 2.0


def _cut(width: float):
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))
    return valley, *bench.notch(valley, crossings, notch_width_m=width, max_depth_m=5.0)


def test_a_width_below_the_cell_size_cuts_the_channel_pixel_alone() -> None:
    valley, out, _ = _cut(4.0)

    assert np.argwhere(out != valley.dem).tolist() == [[ROAD_ROW, bench.AXIS]]


def test_a_width_of_three_cells_cuts_one_cell_each_side_of_the_chain() -> None:
    valley, out, _ = _cut(30.0)

    rows, cols = np.nonzero(out != valley.dem)

    assert set(cols.tolist()) == {bench.AXIS - 1, bench.AXIS, bench.AXIS + 1}
    # Only the row of the embankment is lowered: the width is applied across it.
    assert set(rows.tolist()) == {ROAD_ROW}


def test_the_neighbours_of_the_embankment_fall_to_the_bed_line() -> None:
    valley, out, _ = _cut(30.0)

    for col in (bench.AXIS - 1, bench.AXIS, bench.AXIS + 1):
        assert out[ROAD_ROW, col] == pytest.approx(bench.bed(ROAD_ROW))


def test_a_neighbour_already_below_the_line_stays_where_it_is() -> None:
    valley = bench.build(embankment_rows=(ROAD_ROW,), height=HEIGHT)
    valley.dem[ROAD_ROW, bench.AXIS + 1] = bench.bed(ROAD_ROW) - 1.0
    crossings = bench.structures(("road", bench.road_along(ROAD_ROW)))

    out, _ = bench.notch(valley, crossings, notch_width_m=30.0, max_depth_m=5.0)

    assert out[ROAD_ROW, bench.AXIS + 1] == valley.dem[ROAD_ROW, bench.AXIS + 1]


def test_the_ground_is_never_raised_whatever_the_width() -> None:
    valley, out, _ = _cut(60.0)

    assert (out <= valley.dem).all()
