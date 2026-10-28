"""The crossing notch cuts a road embankment on the channel down to the bed line.

The bench is the valley of ``tests/_helpers/ground_bench.py``: a channel down
column 10, one metre of bed per row, a road raised across the whole width.
"""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import LineString, MultiLineString, box

from hydromodpy.spatial.geographic.core import ground_corrections
from hydromodpy.spatial.geographic.core.ground_corrections import NotchReport, notch_dem
from tests._helpers import ground_bench as bench

ROW = 10
HEIGHT = 2.5
AXIS = bench.AXIS
POND_LEVEL, CREST = 95.0, 100.0


def _road(row: int = ROW, *extra: tuple[str, object], height: float = HEIGHT, rows=None):
    valley = bench.build(embankment_rows=rows or (row,), height=height)
    return valley, bench.structures(("road", bench.road_along(row)), *extra)


def _pond_behind_a_dam():
    """A flat pond on rows 3 to 9, a dam crest on row 10, the channel below it."""
    valley = bench.build()
    valley.dem[3:ROW, :] = np.minimum(valley.dem[3:ROW, :], POND_LEVEL)
    valley.dem[3:ROW, AXIS] = POND_LEVEL
    valley.dem[ROW, :] = CREST
    return valley


def _cut(**options):
    valley, crossings = _road()
    return valley, *bench.notch(valley, crossings, **options)


# --- what is lowered ----------------------------------------------------------


def test_the_embankment_pixel_on_the_channel_alone_falls_to_the_bed_and_is_reported() -> None:
    valley, out, report = _cut()

    assert valley.dem[ROW, AXIS] == pytest.approx(bench.bed(ROW) + HEIGHT)
    assert out[ROW, AXIS] == pytest.approx(bench.bed(ROW))
    assert np.argwhere(out != valley.dem).tolist() == [[ROW, AXIS]]
    assert (out <= valley.dem).all()
    assert report.crossing_points == {"road": 1}
    assert report.notched == {"road": 1}
    assert report.skipped == {}
    assert report.pixels_lowered == 1
    assert report.max_lowering_m == pytest.approx(HEIGHT)
    assert report.median_lowering_m == pytest.approx(HEIGHT)
    assert report.capped_pixels == 0


def test_a_bed_read_on_both_sides_follows_a_sloping_embankment_foot() -> None:
    """The line joins the two bed levels, so a steeper reach is followed, not levelled."""
    valley, crossings = _road()
    valley.dem[ROW + 3, AXIS] -= 1.0

    out, _ = bench.notch(valley, crossings)

    z_up, z_down = valley.dem[ROW - 3, AXIS], valley.dem[ROW + 3, AXIS]
    assert out[ROW, AXIS] == pytest.approx((z_up + z_down) / 2.0)


def _split_network(valley):
    """The extracted vector is cut at its junctions: both pieces touch the road."""
    x, y = bench.x_of(AXIS), bench.y_of(ROW)
    valley.network = gpd.GeoDataFrame(
        geometry=[
            LineString([(x, bench.N * bench.RES - 1.0), (x, y)]),
            LineString([(x, y), (x, 1.0)]),
        ],
        crs=bench.CRS,
    )


def _split_road():
    valley = bench.build(embankment_rows=(ROW,), height=HEIGHT)
    x, y = bench.x_of(AXIS), bench.y_of(ROW)
    return valley, bench.structures(
        ("road", LineString([(0.0, y), (x, y)])),
        ("road", LineString([(x, y), (bench.N * bench.RES, y)])),
    )


def _embanked(*structures):
    return bench.build(embankment_rows=(ROW,), height=HEIGHT), bench.structures(*structures)


def _cut_network():
    valley, crossings = _road()
    _split_network(valley)
    return valley, crossings


ELSEWHERE = LineString([(0.0, bench.y_of(3)), (60.0, bench.y_of(3))])

NOTCHED = {
    "bed reach shorter than asked": (lambda: _road(2, height=2.0), {"bed_reach_m": 50.0}, 2, {}),
    "bridge snapped within the radius": (
        lambda: _embanked(("bridge", bench.bridge_at(AXIS + 2, ROW))),
        {"snap_radius_m": 30.0},
        ROW,
        {"notched": {"bridge": 1}},
    ),
    "bridge reached by a wider radius": (
        lambda: _embanked(("bridge", bench.bridge_at(AXIS + 6, ROW))),
        {"snap_radius_m": 70.0},
        ROW,
        {"notched": {"bridge": 1}},
    ),
    "dam farther than the snap radius": (
        lambda: _road(ROW, ("dam", bench.bridge_at(AXIS + 5, ROW))),
        {"snap_radius_m": 30.0},
        ROW,
        {"notched": {"road": 1}},
    ),
    "lake away from the chain": (_road, {"lakes": [box(0.0, 0.0, 30.0, 30.0)]}, ROW, {}),
    "kind read stripped and in lower case": (
        lambda: _embanked((" Road ", bench.road_along(ROW))),
        {},
        ROW,
        {"features": {"road": 1}},
    ),
    "railway cut like a road": (
        lambda: _embanked(("railway", bench.road_along(ROW))),
        {},
        ROW,
        {"notched": {"railway": 1}},
    ),
    "bridge drawn as a line cut like a road": (
        lambda: _embanked(("bridge", bench.road_along(ROW))),
        {},
        ROW,
        {"notched": {"bridge": 1}},
    ),
    "channel cut at the crossing": (_cut_network, {}, ROW, {"crossing_points": {"road": 1}}),
    "bridge of one source and road of another": (
        lambda: _road(ROW, ("bridge", bench.bridge_at(AXIS + 1, ROW))),
        {},
        ROW,
        {},
    ),
    "road split in two at the stream": (_split_road, {}, ROW, {"crossing_points": {"road": 1}}),
    "road drawn as a multiline": (
        lambda: _embanked(("road", MultiLineString([bench.road_along(ROW), ELSEWHERE]))),
        {},
        ROW,
        {"features": {"road": 1}},
    ),
}


@pytest.mark.parametrize(
    ("case", "options", "row", "expected"), NOTCHED.values(), ids=list(NOTCHED)
)
def test_one_crossing_on_the_channel_is_cut_to_the_bed(case, options, row, expected) -> None:
    valley, crossings = case()

    out, report = bench.notch(valley, crossings, **options)

    assert out[row, AXIS] == pytest.approx(bench.bed(row))
    assert sum(report.crossing_points.values()) == 1
    assert sum(report.notched.values()) == 1
    assert report.skipped == {}
    for name, value in expected.items():
        assert getattr(report, name) == value


def test_a_weir_or_a_dam_drawn_across_the_channel_is_never_cut() -> None:
    valley = bench.build(embankment_rows=(ROW,), height=HEIGHT)
    for kind in ("weir", "dam"):
        out, report = bench.notch(valley, bench.structures((kind, bench.road_along(ROW))))

        assert (out == valley.dem).all(), kind
        assert kind not in report.notched, kind


def test_the_kinds_option_leaves_the_other_kinds_alone() -> None:
    valley, crossings = _road()

    out, report = bench.notch(valley, crossings, kinds=("railway",))

    assert (out == valley.dem).all()
    assert report.features == {}


def test_two_roads_on_one_channel_are_two_notches() -> None:
    valley, crossings = _road(5, ("road", bench.road_along(15)), rows=(5, 15))

    out, report = bench.notch(valley, crossings)

    assert out[5, AXIS] == pytest.approx(bench.bed(5))
    assert out[15, AXIS] == pytest.approx(bench.bed(15))
    assert report.notched == {"road": 2}
    assert report.pixels_lowered == 2


# --- what is left alone -------------------------------------------------------


def _nodata_bed():
    valley, crossings = _road(height=2.0)
    valley.dem[7, AXIS] = -9999.0
    return valley, crossings


def _short_channel():
    valley, crossings = _road()
    valley.streams[:, AXIS] = False
    valley.streams[:4, AXIS] = True
    return valley, crossings


def _lake_on_the_chain():
    pond = box(bench.x_of(AXIS - 4), bench.y_of(ROW - 1), bench.x_of(AXIS + 4), bench.y_of(5))
    return _pond_behind_a_dam(), bench.structures(("road", bench.road_along(ROW))), [pond]


SKIPPED = {
    "channel head": (lambda: _road(0, height=2.0), {}, "no_upstream_reach"),
    "outlet": (lambda: _road(bench.N - 1, height=2.0), {}, "no_downstream_reach"),
    "nodata bed level": (_nodata_bed, {}, "nodata"),
    "bridge beyond the snap radius": (
        lambda: _embanked(("bridge", bench.bridge_at(AXIS + 6, ROW))),
        {"snap_radius_m": 30.0},
        "off_channel",
    ),
    "no channel pixel near the crossing": (_short_channel, {}, "no_channel_pixel"),
    "ground already at the bed line": (
        lambda: (bench.build(), bench.structures(("road", bench.road_along(ROW)))),
        {},
        "nothing_to_lower",
    ),
    "dam declared in the same file": (
        lambda: (
            _pond_behind_a_dam(),
            bench.structures(("road", bench.road_along(ROW)), ("dam", bench.bridge_at(AXIS, ROW))),
        ),
        {},
        "dam_or_weir",
    ),
    "weir within the snap radius": (
        lambda: _road(ROW, ("weir", bench.bridge_at(AXIS + 2, ROW))),
        {"snap_radius_m": 30.0},
        "dam_or_weir",
    ),
    "declared lake on the chain": (
        lambda: _lake_on_the_chain()[:2],
        {"lakes": _lake_on_the_chain()[2]},
        "dam_or_weir",
    ),
    "polygon structure": (
        lambda: _embanked(("road", bench.bridge_at(AXIS, ROW).buffer(5.0))),
        {},
        "unsupported_geometry",
    ),
}


@pytest.mark.parametrize(("case", "options", "reason"), SKIPPED.values(), ids=list(SKIPPED))
def test_a_crossing_that_cannot_be_cut_is_skipped_with_its_reason(case, options, reason) -> None:
    valley, crossings = case()

    out, report = bench.notch(valley, crossings, **options)

    assert np.array_equal(out, valley.dem)
    assert report.skipped == {reason: 1}
    assert report.pixels_lowered == 0
    assert report.skipped_detail[0]["reason"] == reason


def test_a_road_that_stops_before_the_channel_is_not_a_crossing() -> None:
    valley = bench.build(embankment_rows=(ROW,), height=HEIGHT)
    short = LineString([(0.0, bench.y_of(ROW)), (60.0, bench.y_of(ROW))])

    out, report = bench.notch(valley, bench.structures(("road", short)))

    assert (out == valley.dem).all()
    assert report.crossing_points == {}
    assert report.features == {"road": 1}


def test_without_a_channel_vector_a_structure_is_counted_and_nothing_moves() -> None:
    valley, crossings = _road()
    valley.network = gpd.GeoDataFrame(geometry=[], crs=bench.CRS)

    out, report = bench.notch(valley, crossings)

    assert (out == valley.dem).all()
    assert report.features == {"road": 1}
    assert report.crossing_points == {}


def test_a_skip_on_a_dam_names_the_structure_and_its_meaning() -> None:
    valley = _pond_behind_a_dam()
    crossings = bench.structures(
        ("road", bench.road_along(ROW)), ("dam", bench.bridge_at(AXIS, ROW))
    )

    out, report = bench.notch(valley, crossings, kinds=("road",))

    assert np.array_equal(out, valley.dem)
    assert report.crossing_points == {"road": 1}
    assert report.notched == {}
    assert report.capped_pixels == 0
    detail = report.skipped_detail[0]
    assert detail["kind"] == "road"
    assert "dam" in detail["meaning"]
    off = bench.notch(
        valley, bench.structures(("bridge", bench.bridge_at(AXIS + 6, ROW))), snap_radius_m=30.0
    )[1]
    assert off.skipped_detail[0]["kind"] == "bridge"
    assert off.crossing_points == {}


def test_spans_that_do_not_settle_are_skipped_not_cut_against_a_wall(monkeypatch) -> None:
    monkeypatch.setattr(ground_corrections, "_MAX_PLAN_PASSES", 1)
    valley, crossings = _road(8, ("railway", bench.road_along(11)), rows=(8, 11))

    out, report = bench.notch(valley, crossings)

    assert (out == valley.dem).all()
    assert report.skipped == {"no_bed_end": 2}


# --- the kinds ----------------------------------------------------------------


def test_the_kinds_are_the_ones_of_the_data_variable() -> None:
    from hydromodpy.data.variables.crossings.config import KINDS

    assert tuple(KINDS) == ground_corrections._KINDS


@pytest.mark.parametrize(
    ("frame", "reason"),
    [
        (
            lambda: bench.structures(("route", bench.road_along(ROW))),
            r"\['route'\] are not allowed",
        ),
        (lambda: gpd.GeoDataFrame(geometry=[bench.road_along(ROW)], crs=bench.CRS), "no 'kind'"),
    ],
    ids=["unknown kind", "no kind column"],
)
def test_a_crossings_frame_the_data_variable_would_refuse_is_refused(frame, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        bench.notch(bench.build(embankment_rows=(ROW,), height=HEIGHT), frame())


# --- the depth cap ------------------------------------------------------------


@pytest.mark.parametrize(
    ("height", "cap", "lowering", "capped"),
    [(6.0, 3.0, 3.0, 1), (3.0, 3.0, 3.0, 0), (6.0, 10.0, 6.0, 0)],
    ids=["cap bites", "line lands on the cap", "cap above the embankment"],
)
def test_max_depth_bounds_the_lowering_and_a_bitten_pixel_is_reported(
    height, cap, lowering, capped
) -> None:
    valley, crossings = _road(height=height)

    out, report = bench.notch(valley, crossings, max_depth_m=cap)

    assert valley.dem[ROW, AXIS] - out[ROW, AXIS] == pytest.approx(lowering)
    assert report.max_lowering_m == pytest.approx(lowering)
    assert report.capped_pixels == capped


def test_two_notches_over_one_pixel_never_exceed_the_cap_together() -> None:
    """A road and a bridge at the same crossing lower the pixel once, to the cap at most."""
    valley, crossings = _road(ROW, ("bridge", bench.bridge_at(AXIS, ROW)), height=6.0)

    out, _ = bench.notch(valley, crossings, max_depth_m=3.0)

    assert valley.dem[ROW, AXIS] - out[ROW, AXIS] == pytest.approx(3.0)


# --- the bed reach ------------------------------------------------------------

JUNCTION_ROW, TRIBUTARY_BED = 12, 60.0


def _forked(*, tributary_acc: float, main_acc: float = 2.0):
    """The main channel with a tributary from the east joining at the junction row."""
    valley, crossings = _road(14, height=2.0)
    for col in range(AXIS + 1, AXIS + 6):
        valley.streams[JUNCTION_ROW, col] = True
        valley.d8[JUNCTION_ROW, col] = bench.WEST
        valley.acc[JUNCTION_ROW, col] = tributary_acc
        valley.dem[JUNCTION_ROW, col] = TRIBUTARY_BED
    valley.acc[JUNCTION_ROW - 1, AXIS] = main_acc
    out, _ = bench.notch(valley, crossings, bed_reach_m=40.0, max_depth_m=30.0)
    return valley, out


def test_upstream_the_walk_climbs_the_branch_that_drains_the_larger_area() -> None:
    valley, out = _forked(tributary_acc=50.0)

    # 13 (10 m), the junction row (20 m), then east along the tributary: 30 m and 40 m.
    z_down = bench.bed(14 + 4)
    assert out[14, AXIS] == pytest.approx(TRIBUTARY_BED + (z_down - TRIBUTARY_BED) * 0.5)
    assert (out[JUNCTION_ROW, AXIS + 1 :] == valley.dem[JUNCTION_ROW, AXIS + 1 :]).all()
    _, out = _forked(tributary_acc=1.0, main_acc=11.0)
    assert out[14, AXIS] == pytest.approx(bench.bed(14))


@pytest.mark.parametrize(
    ("rows", "options"),
    [((8, 11), {}), ((9, 10), {}), ((8, 12), {"bed_reach_m": 60.0})],
    ids=["thirty metres apart", "one cell apart", "reach over both"],
)
def test_two_structures_within_the_bed_reach_do_not_read_each_other_as_the_bed(
    rows, options
) -> None:
    valley, crossings = _road(rows[0], ("railway", bench.road_along(rows[1])), rows=rows)

    out, report = bench.notch(valley, crossings, **options)

    for row in rows:
        assert out[row, AXIS] == pytest.approx(bench.bed(row))
    assert (out[rows[0] + 1 : rows[1], :] == valley.dem[rows[0] + 1 : rows[1], :]).all()
    if rows == (8, 11):
        assert report.skipped == {}
        assert report.notched == {"road": 1, "railway": 1}
        assert report.pixels_lowered == 2


# --- the notch width ----------------------------------------------------------


def test_a_width_below_the_cell_size_cuts_the_channel_pixel_alone() -> None:
    valley, out, _ = _cut(notch_width_m=4.0, max_depth_m=5.0)

    assert np.argwhere(out != valley.dem).tolist() == [[ROW, AXIS]]


@pytest.mark.parametrize("width", [30.0, 60.0])
def test_a_wide_notch_lowers_the_neighbours_across_the_embankment_only(width) -> None:
    valley, out, _ = _cut(notch_width_m=width, max_depth_m=5.0)

    rows, cols = np.nonzero(out != valley.dem)
    assert set(rows.tolist()) == {ROW}
    half = int(width // bench.RES) // 2
    assert set(cols.tolist()) == set(range(AXIS - half, AXIS + half + 1))
    for col in set(cols.tolist()):
        assert out[ROW, col] == pytest.approx(bench.bed(ROW))
    assert (out <= valley.dem).all()
    # The reach is 30 m: the up end (7, 10) and the pixel beside it stay.
    assert out[7, AXIS] == valley.dem[7, AXIS]
    assert out[7, AXIS - 1] == valley.dem[7, AXIS - 1]


def test_a_neighbour_already_below_the_line_stays_where_it_is() -> None:
    valley, crossings = _road(height=2.0)
    valley.dem[ROW, AXIS + 1] = bench.bed(ROW) - 1.0

    out, _ = bench.notch(valley, crossings, notch_width_m=30.0, max_depth_m=5.0)

    assert out[ROW, AXIS + 1] == valley.dem[ROW, AXIS + 1]


RES5, N5, AXIS5, ROAD5 = 5.0, 61, 30, 30


def _notch_five_metres(width: float):
    """A 5 m DEM: banks 1 m above a concave bed, a 15 m embankment on three rows."""
    transform = from_origin(0.0, N5 * RES5, RES5, RES5)
    rows, cols = np.arange(N5)[:, None], np.arange(N5)[None, :]
    bed = 100.0 - 0.05 * rows + 0.0004 * rows**2
    dem = (bed + np.where(cols == AXIS5, 0.0, 1.0 + 0.2 * np.abs(cols - AXIS5))).astype("float32")
    dem[ROAD5 - 1 : ROAD5 + 2, :] += 2.0
    streams = np.zeros((N5, N5), bool)
    streams[:, AXIS5] = True
    d8 = np.full((N5, N5), 8, int)
    d8[N5 - 1, :] = 0
    acc = np.ones((N5, N5))
    acc[:, AXIS5] = np.arange(1, N5 + 1)
    x, y = (AXIS5 + 0.5) * RES5, N5 * RES5 - (ROAD5 + 0.5) * RES5
    network = gpd.GeoDataFrame(geometry=[LineString([(x, N5 * RES5 - 1), (x, 1)])], crs=bench.CRS)
    report = NotchReport(parameters={})
    out, _ = notch_dem(
        dem,
        nodata=-9999.0,
        transform=transform,
        streams=streams,
        d8=d8,
        acc=acc,
        crossings=bench.structures(("road", LineString([(0, y), (N5 * RES5, y)]))),
        network=network,
        kinds=["road"],
        notch_width_m=width,
        bed_reach_m=50.0,
        max_depth_m=5.0,
        snap_radius_m=30.0,
        report=report,
    )
    return dem, out, report


def test_on_a_five_metre_dem_only_the_embankment_and_one_pixel_each_side_fall() -> None:
    dem, out, report = _notch_five_metres(10.0)

    moved = np.argwhere(out < dem - 1e-4)
    assert set(moved[:, 0].tolist()) == {ROAD5 - 1, ROAD5, ROAD5 + 1}
    assert set(moved[:, 1].tolist()) == {AXIS5 - 1, AXIS5, AXIS5 + 1}
    assert report.pixels_lowered == 9
    # The bed is not a straight line, so a bank pixel takes the level of its own row.
    levels = [out[row, AXIS5 - 1] for row in (ROAD5 - 1, ROAD5, ROAD5 + 1)]
    assert out[ROAD5, AXIS5] == pytest.approx(out[ROAD5, AXIS5 + 1])
    assert len({round(float(level), 4) for level in levels}) == 3
    assert (out <= dem).all()


@pytest.mark.parametrize("width", [10.0, 20.0, 40.0])
def test_the_two_end_pixels_of_the_reach_are_never_lowered(width: float) -> None:
    dem, out, _ = _notch_five_metres(width)

    # The reach is 50 m: the ends are ten pixels on each side of the crossing.
    for row in (ROAD5 - 10, ROAD5 + 10):
        assert (out[row, :] == dem[row, :]).all()
