"""The bed regularisation moves the channel pixels only, and leaves no rise along them.

A synthetic valley on a 25 m grid: a main stem down the middle column and a
tributary joining it from the west, both carrying a gentle bed plus a
symmetric noise larger than the drop between two pixels. The hillslopes stand
well above the bed and are not on the tree.
"""

from __future__ import annotations

import numpy as np
import pytest
from rasterio.transform import from_origin

from hydromodpy.spatial.geographic.core.bed_regularization_raster import (
    pixel_tree,
    regularize_channel_bed,
)

ROWS, COLS = 40, 21
RES = 25.0
AXIS = 10
JUNCTION = 15
TRANSFORM = from_origin(0.0, ROWS * RES, RES, RES)
EAST, SOUTH = 2, 8
MIN_SLOPE = 1.0e-4


def _valley(seed: int = 7, sd: float = 0.4) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    rows = np.arange(ROWS)[:, None]
    cols = np.arange(COLS)[None, :]
    top = 100.0 - 0.004 * RES * rows + 2.0 * np.abs(cols - AXIS) + 0.5
    channel = np.zeros((ROWS, COLS), dtype=bool)
    channel[:, AXIS] = True
    channel[JUNCTION, 2:AXIS] = True
    d8 = np.where(cols < AXIS, EAST, 32) * np.ones((ROWS, 1), dtype=int)
    d8[:, AXIS] = SOUTH
    d8[ROWS - 1, AXIS] = 0
    bed = np.full((ROWS, COLS), np.nan)
    bed[:, AXIS] = 100.0 - 0.004 * RES * np.arange(ROWS)
    bed[JUNCTION, 2:AXIS] = bed[JUNCTION, AXIS] + 0.01 * RES * (AXIS - np.arange(2, AXIS))
    noise = np.random.default_rng(seed).normal(0.0, sd, size=(ROWS, COLS))
    top = np.where(channel, bed + noise, top).astype("float32")
    return top, channel, d8


def _fit():
    top, channel, d8 = _valley()
    valid = np.ones_like(channel)
    out, report = regularize_channel_bed(
        top, valid=valid, transform=TRANSFORM, channel=channel, d8=d8, min_slope=MIN_SLOPE
    )
    return top, channel, d8, out, report


def test_only_channel_pixels_move() -> None:
    top, channel, _, out, report = _fit()

    moved = out != top
    assert moved.any()
    assert not (moved & ~channel).any()
    assert out.dtype == top.dtype
    assert report.channel_pixels == int(channel.sum())


def test_no_edge_of_the_tree_rises_downstream() -> None:
    top, channel, d8, out, report = _fit()
    tree = pixel_tree(channel, d8, res_x=RES, res_y=RES)
    edges = np.flatnonzero(tree.receiver >= 0)
    upstream = out[tree.rows[edges], tree.cols[edges]].astype(float)
    receiver = tree.receiver[edges]
    downstream = out[tree.rows[receiver], tree.cols[receiver]].astype(float)

    raw_rise = (
        top[tree.rows[edges], tree.cols[edges]] < top[tree.rows[receiver], tree.cols[receiver]]
    )
    assert raw_rise.sum() > 10
    assert report.violations_before > 10
    assert report.rises_after_fit == 0
    # float32 holds a 100 m bed to about 1e-5 m.
    assert (upstream - downstream >= MIN_SLOPE * tree.edge_length[edges] - 1e-4).all()


def test_the_fit_keeps_the_mean_of_the_bed() -> None:
    _, _, _, _, report = _fit()

    assert report.raised > 0 and report.lowered > 0
    assert abs(report.mean_bias_m) < 0.01


def test_the_tree_has_one_root_and_joins_the_tributary_at_the_junction() -> None:
    _, channel, d8 = _valley()

    tree = pixel_tree(channel, d8, res_x=RES, res_y=RES)

    assert int((tree.receiver < 0).sum()) == 1
    last = np.flatnonzero((tree.rows == JUNCTION) & (tree.cols == AXIS - 1))[0]
    junction = tree.receiver[last]
    assert (tree.rows[junction], tree.cols[junction]) == (JUNCTION, AXIS)
    assert tree.edge_length[last] == pytest.approx(RES)


def test_a_diagonal_pointer_is_a_longer_edge() -> None:
    channel = np.zeros((3, 3), dtype=bool)
    channel[0, 0] = channel[1, 1] = True
    d8 = np.zeros((3, 3), dtype=int)
    d8[0, 0] = 4  # south-east

    tree = pixel_tree(channel, d8, res_x=RES, res_y=RES)

    first = np.flatnonzero((tree.rows == 0) & (tree.cols == 0))[0]
    assert tree.edge_length[first] == pytest.approx(RES * np.sqrt(2.0))


def test_a_bump_at_the_junction_is_reported_as_a_confluence_block() -> None:
    top, channel, d8 = _valley(sd=0.0)
    top[JUNCTION, AXIS] += 1.0

    _, report = regularize_channel_bed(
        top,
        valid=np.ones_like(channel),
        transform=TRANSFORM,
        channel=channel,
        d8=d8,
        min_slope=MIN_SLOPE,
    )

    amplitudes = [block["amplitude_m"] for block in report.confluence_blocks]
    assert amplitudes
    assert amplitudes == sorted(amplitudes, reverse=True)
    junction_xy = [(AXIS + 0.5) * RES, (ROWS - JUNCTION - 0.5) * RES]
    held = [block for block in report.confluence_blocks if junction_xy in block["confluences"]]
    assert len(held) == 1
    assert held[0]["pixels"] >= 3
    assert held[0]["max_raise_m"] > 0.2
    assert held[0]["max_lowering_m"] > 0.5
