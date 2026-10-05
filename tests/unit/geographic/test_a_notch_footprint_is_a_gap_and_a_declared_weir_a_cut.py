"""A notched crossing is a gap of the bed and a declared weir or dam cuts the tree.

A straight channel down the middle column of a 25 m grid. The gap case puts a
capped embankment on the bed; the weir case is the reach of a weir with a 2 m
drop and an undeclared bump below its foot; the dam case is a pond held by a
crest 10 m above it.
"""

from __future__ import annotations

import numpy as np
import pytest
from rasterio.transform import from_origin, xy
from shapely.geometry import Point, box

from hydromodpy.spatial.geographic.core.bed_regularization_raster import (
    regularize_channel_bed,
)

RES = 25.0
AXIS = 1
SOUTH = 8


def _column(values: list[float]) -> tuple[np.ndarray, np.ndarray, np.ndarray, object]:
    rows = len(values)
    transform = from_origin(0.0, rows * RES, RES, RES)
    top = np.full((rows, 3), 200.0, dtype="float32")
    top[:, AXIS] = values
    channel = np.zeros((rows, 3), dtype=bool)
    channel[:, AXIS] = True
    d8 = np.full((rows, 3), SOUTH, dtype=int)
    d8[-1, :] = 0
    return top, channel, d8, transform


def _fit(top, channel, d8, transform, **kwargs):
    return regularize_channel_bed(
        top, valid=np.ones_like(channel), transform=transform, channel=channel, d8=d8, **kwargs
    )


def _point(transform, row: int, dx: float = 0.0) -> Point:
    x, y = xy(transform, row, AXIS)
    return Point(x + dx, y)


# --- gaps ---------------------------------------------------------------------

BED = [10.0 - 0.25 * i for i in range(11)]
EMBANKMENT = 5


def test_a_footprint_pixel_follows_the_line_of_its_measured_neighbours() -> None:
    values = list(BED)
    values[EMBANKMENT] += 1.5  # what the cap of the notch left of the embankment
    top, channel, d8, transform = _column(values)
    gap = np.zeros_like(channel)
    gap[EMBANKMENT, AXIS] = True

    as_bump, _ = _fit(top, channel, d8, transform)
    out, report = _fit(top, channel, d8, transform, gap=gap)

    assert as_bump[EMBANKMENT - 1, AXIS] > BED[EMBANKMENT - 1] + 0.4
    np.testing.assert_allclose(out[:, AXIS], BED, atol=1e-5)
    assert report.gap_pixels == 1
    assert (report.raised, report.lowered) == (0, 0)


# --- cuts ---------------------------------------------------------------------

# 0 (head) -> 1 -> 2 (weir crest) -> 3 (foot) -> 4 (bump) -> 5 (root).
WEIR_REACH = [12.5, 12.2, 12.0, 10.0, 15.0, 9.0]
WEIR = 2


def _weirs(transform, *, dx: float = 0.0):
    return [("weir", "moulin", 2.0, _point(transform, WEIR, dx))]


def test_a_declared_weir_keeps_the_reach_above_its_drop() -> None:
    top, channel, d8, transform = _column(WEIR_REACH)

    uncut, _ = _fit(top, channel, d8, transform)
    out, report = _fit(top, channel, d8, transform, barriers=_weirs(transform))

    assert uncut[WEIR, AXIS] > WEIR_REACH[WEIR] + 0.1
    np.testing.assert_allclose(out[: WEIR + 1, AXIS], WEIR_REACH[: WEIR + 1])
    assert report.climbs_at_cuts == 1
    assert report.violations_after == 0
    (cut,) = report.cuts
    assert (cut["kind"], cut["name"], cut["drop_m"]) == ("weir", "moulin", 2.0)
    # The foot is pooled with the bump and tilted about their mean.
    assert cut["climb_m"] == pytest.approx(12.5 + 1.0e-4 * RES / 2 - 12.0, abs=1e-4)


def test_a_weir_snaps_to_the_nearest_channel_pixel_within_the_radius() -> None:
    top, channel, d8, transform = _column(WEIR_REACH)

    out, report = _fit(
        top, channel, d8, transform, barriers=_weirs(transform, dx=20.0), snap_radius_m=30.0
    )

    assert len(report.cuts) == 1
    np.testing.assert_allclose(out[: WEIR + 1, AXIS], WEIR_REACH[: WEIR + 1])


def test_a_weir_beyond_the_radius_does_not_cut() -> None:
    top, channel, d8, transform = _column(WEIR_REACH)

    out, report = _fit(
        top, channel, d8, transform, barriers=_weirs(transform, dx=40.0), snap_radius_m=30.0
    )

    assert report.cuts == []
    assert report.barriers_skipped == {"off_channel": 1}
    assert out[WEIR, AXIS] > WEIR_REACH[WEIR] + 0.1


def test_a_weir_inside_a_declared_lake_does_not_cut() -> None:
    top, channel, d8, transform = _column(WEIR_REACH)
    rows = len(WEIR_REACH)
    lake = box(0.0, (rows - WEIR - 2) * RES, 3 * RES, (rows - WEIR) * RES)

    out, report = _fit(top, channel, d8, transform, barriers=_weirs(transform), lakes=[lake])

    assert report.cuts == []
    assert report.barriers_skipped == {"in_lake": 1}
    assert report.lake_pixels == 2
    np.testing.assert_array_equal(out[WEIR : WEIR + 2, AXIS], top[WEIR : WEIR + 2, AXIS])


def test_two_barriers_on_one_pixel_cut_it_once_and_say_so() -> None:
    top, channel, d8, transform = _column(WEIR_REACH)
    barriers = _weirs(transform) + [("dam", "", float("nan"), _point(transform, WEIR, 5.0))]

    _, report = _fit(top, channel, d8, transform, barriers=barriers)

    assert len(report.cuts) == 1
    assert report.barriers_skipped == {"same_pixel": 1}


# --- a dam above its pond -----------------------------------------------------

POND = 40
CREST = POND
POND_LEVEL, CREST_LEVEL, VALLEY = 300.0, 310.0, 280.0
DAM_REACH = [POND_LEVEL] * POND + [CREST_LEVEL] + [VALLEY - 0.1 * i for i in range(10)]


@pytest.mark.parametrize("snapped", [CREST, CREST - 1], ids=["crest", "pond-side foot"])
def test_a_dam_snapped_to_its_crest_or_its_foot_leaves_the_pond_untouched(snapped) -> None:
    top, channel, d8, transform = _column(DAM_REACH)
    dam = [("dam", "barrage", 10.0, _point(transform, snapped))]

    uncut, _ = _fit(top, channel, d8, transform)
    out, report = _fit(top, channel, d8, transform, barriers=dam)

    assert uncut[: POND - 1, AXIS].mean() > POND_LEVEL + 0.2
    # The pond above the snapped pixel is a tree of its own, tilted about its level.
    pond = out[:snapped, AXIS].astype(float)
    np.testing.assert_allclose(pond.mean(), POND_LEVEL, atol=1e-4)
    assert pond.max() - pond.min() <= 1.0e-4 * RES * (snapped - 1) + 1e-4
    np.testing.assert_array_equal(out[snapped : CREST + 1, AXIS], top[snapped : CREST + 1, AXIS])
    assert len(report.cuts) == 1


# --- a declared lake ----------------------------------------------------------

LAKE_ROWS = slice(5, 15)
LAKE_REACH = (
    [306.0, 305.0, 305.4, 304.0, 303.0] + [300.0] * 10 + [299.0, 298.0, 298.6, 297.0, 296.0]
)


def test_a_declared_lake_keeps_its_surface_and_cuts_the_tree() -> None:
    top, channel, d8, transform = _column(LAKE_REACH)
    rows = len(LAKE_REACH)
    lake = box(0.0, (rows - LAKE_ROWS.stop) * RES, 3 * RES, (rows - LAKE_ROWS.start) * RES)

    out, report = _fit(top, channel, d8, transform, lakes=[lake])

    np.testing.assert_array_equal(out[LAKE_ROWS, AXIS], top[LAKE_ROWS, AXIS])
    assert report.lake_pixels == 10
    assert report.channel_pixels == rows - 10
    for reach in (slice(0, LAKE_ROWS.start), slice(LAKE_ROWS.stop, rows)):
        bed = out[reach, AXIS].astype(float)
        assert (np.diff(bed) < 0).all()
    assert report.rises_after_fit == 0
