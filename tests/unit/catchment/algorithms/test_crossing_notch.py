"""The crossing notch cuts a road embankment on the channel down to the bed line.

The bench is the valley of ``tests/_helpers/ground_bench.py``: a channel down
column 10, one meter of bed per row, a road raised across the whole width.
"""

import geopandas as gpd
import numpy as np
import pytest
from rasterio.transform import from_origin
from shapely.geometry import LineString, MultiLineString, box

from hydromodpy.catchment.algorithms import crossing_notch
from hydromodpy.catchment.algorithms.crossing_notch import NotchReport, notch_dem
from tests._helpers import ground_bench as bench

ROW, HEIGHT, AXIS = 10, 2.5, bench.AXIS
POND_LEVEL, CREST = 95.0, 100.0
X, Y = bench.x_of(AXIS), bench.y_of(ROW)
ELSEWHERE = LineString([(0.0, bench.y_of(3)), (60.0, bench.y_of(3))])
SHORT_ROAD = LineString([(0.0, Y), (60.0, Y)])


def _road(row: int = ROW, *extra: tuple[str, object], height: float = HEIGHT, rows=None):
    valley = bench.build(embankment_rows=rows or (row,), height=height)
    return valley, bench.structures(("road", bench.road_along(row)), *extra)


def _embanked(*structures):
    return bench.build(embankment_rows=(ROW,), height=HEIGHT), bench.structures(*structures)


def _along(kind: str, line=None, *extra: tuple[str, object]):
    return _embanked((kind, line or bench.road_along(ROW)), *extra)


def _at(kind: str, col: int):
    return _embanked((kind, bench.bridge_at(col, ROW)))


def _pond_behind_a_dam():
    """A flat pond on rows 3 to 9, a dam crest on row 10, the channel below it."""
    valley = bench.build()
    valley.dem[3:ROW, :] = np.minimum(valley.dem[3:ROW, :], POND_LEVEL)
    valley.dem[3:ROW, AXIS] = POND_LEVEL
    valley.dem[ROW, :] = CREST
    return valley


def _cut_network():
    """The extracted vector is cut at its junctions: both pieces touch the road."""
    valley, crossings = _road()
    lines = [LineString([(X, bench.N * bench.RES - 1.0), (X, Y)]), LineString([(X, Y), (X, 1.0)])]
    valley.network = gpd.GeoDataFrame(geometry=lines, crs=bench.CRS)
    return valley, crossings


def _split_road():
    halves = LineString([(0.0, Y), (X, Y)]), LineString([(X, Y), (bench.N * bench.RES, Y)])
    return _embanked(*(("road", half) for half in halves))


def _no_network():
    valley, crossings = _road()
    valley.network = gpd.GeoDataFrame(geometry=[], crs=bench.CRS)
    return valley, crossings


def _cut(**options):
    valley, crossings = _road()
    return valley, *bench.notch(valley, crossings, **options)


def test_embankment_cut_to_the_bed() -> None:
    valley, out, report = _cut()
    assert valley.dem[ROW, AXIS] == pytest.approx(bench.bed(ROW) + HEIGHT)
    assert out[ROW, AXIS] == pytest.approx(bench.bed(ROW))
    assert np.argwhere(out != valley.dem).tolist() == [[ROW, AXIS]]
    assert (out <= valley.dem).all()
    assert (report.crossing_points, report.notched, report.skipped) == ({"road": 1},) * 2 + ({},)
    assert (report.pixels_lowered, report.capped_pixels) == (1, 0)
    assert report.max_lowering_m == pytest.approx(HEIGHT)
    assert report.median_lowering_m == pytest.approx(HEIGHT)


def test_bed_on_both_sides() -> None:
    """The line joins the two bed levels, so a steeper reach is followed, not levelled."""
    valley, crossings = _road()
    valley.dem[ROW + 3, AXIS] -= 1.0
    out, _ = bench.notch(valley, crossings)
    assert out[ROW, AXIS] == pytest.approx(
        (valley.dem[ROW - 3, AXIS] + valley.dem[ROW + 3, AXIS]) / 2
    )


# fmt: off
NOTCHED = {
    "bed reach shorter than asked": (lambda: _road(2, height=2.0), {"bed_reach_m": 50.0}, 2, {}),
    "bridge snapped within the radius": (lambda: _at("bridge", AXIS + 2), {"snap_radius_m": 30.0}, ROW, {"notched": {"bridge": 1}}),
    "bridge reached by a wider radius": (lambda: _at("bridge", AXIS + 6), {"snap_radius_m": 70.0}, ROW, {"notched": {"bridge": 1}}),
    "dam farther than the snap radius": (lambda: _road(ROW, ("dam", bench.bridge_at(AXIS + 5, ROW))), {"snap_radius_m": 30.0}, ROW, {"notched": {"road": 1}}),
    "lake away from the chain": (_road, {"lakes": [box(0.0, 0.0, 30.0, 30.0)]}, ROW, {}),
    "kind read stripped and in lower case": (lambda: _along(" Road "), {}, ROW, {"features": {"road": 1}}),
    "railway cut like a road": (lambda: _along("railway"), {}, ROW, {"notched": {"railway": 1}}),
    "bridge drawn as a line cut like a road": (lambda: _along("bridge"), {}, ROW, {"notched": {"bridge": 1}}),
    "channel cut at the crossing": (_cut_network, {}, ROW, {"crossing_points": {"road": 1}}),
    "bridge of one source and road of another": (lambda: _road(ROW, ("bridge", bench.bridge_at(AXIS + 1, ROW))), {}, ROW, {}),
    "road split in two at the stream": (_split_road, {}, ROW, {"crossing_points": {"road": 1}}),
    "road drawn as a multiline": (lambda: _along("road", MultiLineString([bench.road_along(ROW), ELSEWHERE])), {}, ROW, {"features": {"road": 1}}),
}
# fmt: on


@pytest.mark.parametrize(
    ("case", "options", "row", "expected"), NOTCHED.values(), ids=list(NOTCHED)
)
def test_one_crossing_cut(case, options, row, expected) -> None:
    valley, crossings = case()
    out, report = bench.notch(valley, crossings, **options)
    assert out[row, AXIS] == pytest.approx(bench.bed(row))
    assert sum(report.crossing_points.values()) == sum(report.notched.values()) == 1
    assert report.skipped == {}
    for name, value in expected.items():
        assert getattr(report, name) == value


# fmt: off
UNTOUCHED = {
    "weir drawn across the channel": (lambda: _along("weir"), {}, {"notched": {}}),
    "dam drawn across the channel": (lambda: _along("dam"), {}, {"notched": {}}),
    "kind left out by the kinds option": (_road, {"kinds": ("railway",)}, {"features": {}}),
    "road stopping before the channel": (lambda: _along("road", SHORT_ROAD), {}, {"crossing_points": {}, "features": {"road": 1}}),
    "no channel vector": (_no_network, {}, {"crossing_points": {}, "features": {"road": 1}}),
}
# fmt: on


@pytest.mark.parametrize(("case", "options", "expected"), UNTOUCHED.values(), ids=list(UNTOUCHED))
def test_no_crossing_no_cut(case, options, expected):
    valley, crossings = case()
    out, report = bench.notch(valley, crossings, **options)
    assert (out == valley.dem).all()
    for name, value in expected.items():
        assert getattr(report, name) == value


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


# fmt: off
SKIPPED = {
    "channel head": (lambda: _road(0, height=2.0), {}, "no_upstream_reach"),
    "outlet": (lambda: _road(bench.N - 1, height=2.0), {}, "no_downstream_reach"),
    "nodata bed level": (_nodata_bed, {}, "nodata"),
    "bridge beyond the snap radius": (lambda: _at("bridge", AXIS + 6), {"snap_radius_m": 30.0}, "off_channel"),
    "no channel pixel near the crossing": (_short_channel, {}, "no_channel_pixel"),
    "ground already at the bed line": (lambda: (bench.build(), _along("road")[1]), {}, "nothing_to_lower"),
    "dam declared in the same file": (lambda: (_pond_behind_a_dam(), _along("road", None, ("dam", bench.bridge_at(AXIS, ROW)))[1]), {}, "dam_or_weir"),
    "weir within the snap radius": (lambda: _road(ROW, ("weir", bench.bridge_at(AXIS + 2, ROW))), {"snap_radius_m": 30.0}, "dam_or_weir"),
    "declared lake on the chain": (lambda: _lake_on_the_chain()[:2], {"lakes": _lake_on_the_chain()[2]}, "dam_or_weir"),
    "polygon structure": (lambda: _embanked(("road", bench.bridge_at(AXIS, ROW).buffer(5.0))), {}, "unsupported_geometry"),
}
# fmt: on


@pytest.mark.parametrize(("case", "options", "reason"), SKIPPED.values(), ids=list(SKIPPED))
def test_skipped_crossings(case, options, reason) -> None:
    valley, crossings = case()
    out, report = bench.notch(valley, crossings, **options)
    assert np.array_equal(out, valley.dem)
    assert (report.skipped, report.pixels_lowered) == ({reason: 1}, 0)
    assert report.skipped_detail[0]["reason"] == reason


def test_dam_skip_message() -> None:
    valley = _pond_behind_a_dam()
    road_and_dam = ("road", bench.road_along(ROW)), ("dam", bench.bridge_at(AXIS, ROW))
    out, report = bench.notch(valley, bench.structures(*road_and_dam), kinds=("road",))
    off = bench.notch(valley, _at("bridge", AXIS + 6)[1], snap_radius_m=30.0)[1]
    assert np.array_equal(out, valley.dem)
    assert (report.crossing_points, report.notched, report.capped_pixels) == ({"road": 1}, {}, 0)
    assert report.skipped_detail[0]["kind"] == "road"
    assert "dam" in report.skipped_detail[0]["meaning"]
    assert (off.skipped_detail[0]["kind"], off.crossing_points) == ("bridge", {})


def test_unsettled_spans_skipped(monkeypatch) -> None:
    monkeypatch.setattr(crossing_notch, "_MAX_PLAN_PASSES", 1)
    valley, crossings = _road(8, ("railway", bench.road_along(11)), rows=(8, 11))
    out, report = bench.notch(valley, crossings)
    assert (out == valley.dem).all()
    assert report.skipped == {"no_bed_end": 2}


def test_kinds() -> None:
    from hydromodpy.data.variables.crossings.config import KINDS

    assert tuple(KINDS) == crossing_notch._KINDS


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
def test_refusals(frame, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        bench.notch(bench.build(embankment_rows=(ROW,), height=HEIGHT), frame())


@pytest.mark.parametrize(
    ("height", "cap", "extra", "lowering", "capped"),
    [
        (6.0, 3.0, (), 3.0, 1),
        (3.0, 3.0, (), 3.0, 0),
        (6.0, 10.0, (), 6.0, 0),
        (6.0, 3.0, (("bridge", bench.bridge_at(AXIS, ROW)),), 3.0, 1),
    ],
    ids=["cap bites", "line lands on the cap", "cap above the embankment", "two over one pixel"],
)
def test_max_depth(height, cap, extra, lowering, capped) -> None:
    """A road and a bridge at the same crossing lower the pixel once, to the cap at most."""
    valley, crossings = _road(ROW, *extra, height=height)
    out, report = bench.notch(valley, crossings, max_depth_m=cap)
    assert valley.dem[ROW, AXIS] - out[ROW, AXIS] == pytest.approx(lowering)
    assert report.max_lowering_m == pytest.approx(lowering)
    assert report.capped_pixels == capped


JUNCTION_ROW, TRIBUTARY_BED = 12, 60.0


def _forked(*, tributary_acc: float, main_acc: float = 2.0):
    """The main channel with a tributary from the east joining at the junction row."""
    valley, crossings = _road(14, height=2.0)
    tributary = (JUNCTION_ROW, slice(AXIS + 1, AXIS + 6))
    valley.streams[tributary], valley.d8[tributary] = True, bench.WEST
    valley.acc[tributary], valley.dem[tributary] = tributary_acc, TRIBUTARY_BED
    valley.acc[JUNCTION_ROW - 1, AXIS] = main_acc
    return valley, bench.notch(valley, crossings, bed_reach_m=40.0, max_depth_m=30.0)[0]


def test_walk_climbs_the_larger_branch() -> None:
    valley, out = _forked(tributary_acc=50.0)
    # 13 (10 m), the junction row (20 m), then east along the tributary: 30 m and 40 m.
    z_down = bench.bed(14 + 4)
    assert out[14, AXIS] == pytest.approx(TRIBUTARY_BED + (z_down - TRIBUTARY_BED) * 0.5)
    assert (out[JUNCTION_ROW, AXIS + 1 :] == valley.dem[JUNCTION_ROW, AXIS + 1 :]).all()
    assert _forked(tributary_acc=1.0, main_acc=11.0)[1][14, AXIS] == pytest.approx(bench.bed(14))


@pytest.mark.parametrize(
    ("rows", "second", "options", "notched"),
    [
        ((5, 15), "road", {}, {"road": 2}),
        ((8, 11), "railway", {}, {"road": 1, "railway": 1}),
        ((9, 10), "railway", {}, None),
        ((8, 12), "railway", {"bed_reach_m": 60.0}, None),
    ],
    ids=["two roads far apart", "thirty metres apart", "one cell apart", "reach over both"],
)
def test_two_notches_are_independent(rows, second, options, notched) -> None:
    valley, crossings = _road(rows[0], (second, bench.road_along(rows[1])), rows=rows)
    out, report = bench.notch(valley, crossings, **options)
    for row in rows:
        assert out[row, AXIS] == pytest.approx(bench.bed(row))
    assert (out[rows[0] + 1 : rows[1], :] == valley.dem[rows[0] + 1 : rows[1], :]).all()
    if notched is not None:
        assert (report.skipped, report.notched, report.pixels_lowered) == ({}, notched, 2)


@pytest.mark.parametrize("width", [4.0, 30.0, 60.0], ids=["below the cell size", "30 m", "60 m"])
def test_notch_width(width) -> None:
    valley, out, _ = _cut(notch_width_m=width, max_depth_m=5.0)
    rows, cols = np.nonzero(out != valley.dem)
    assert set(rows.tolist()) == {ROW}
    half = int(width // bench.RES) // 2
    assert set(cols.tolist()) == set(range(AXIS - half, AXIS + half + 1))
    for col in set(cols.tolist()):
        assert out[ROW, col] == pytest.approx(bench.bed(ROW))
    assert (out <= valley.dem).all()
    # The reach is 30 m: the up end (7, 10) and the pixel beside it stay.
    assert (out[7, AXIS - 1 : AXIS + 1] == valley.dem[7, AXIS - 1 : AXIS + 1]).all()


RES5, N5, AXIS5, ROAD5 = 5.0, 61, 30, 30


@pytest.mark.parametrize("width", [10.0, 20.0, 40.0])
def test_five_metre_dem(width) -> None:
    """A 5 m DEM: banks 1 m above a concave bed, a 15 m embankment on three rows."""
    rows, cols = np.arange(N5)[:, None], np.arange(N5)[None, :]
    bed = 100.0 - 0.05 * rows + 0.0004 * rows**2
    dem = (bed + np.where(cols == AXIS5, 0.0, 1.0 + 0.2 * np.abs(cols - AXIS5))).astype("float32")
    dem[ROAD5 - 1 : ROAD5 + 2, :] += 2.0
    streams, d8, acc = np.zeros((N5, N5), bool), np.full((N5, N5), 8, int), np.ones((N5, N5))
    streams[:, AXIS5], d8[N5 - 1, :], acc[:, AXIS5] = True, 0, np.arange(1, N5 + 1)
    x, y = (AXIS5 + 0.5) * RES5, N5 * RES5 - (ROAD5 + 0.5) * RES5
    network = gpd.GeoDataFrame(geometry=[LineString([(x, N5 * RES5 - 1), (x, 1)])], crs=bench.CRS)
    road = bench.structures(("road", LineString([(0, y), (N5 * RES5, y)])))
    report = NotchReport(parameters={})
    out, _ = notch_dem(
        dem, nodata=-9999.0, transform=from_origin(0.0, N5 * RES5, RES5, RES5), streams=streams,
        d8=d8, acc=acc, crossings=road, network=network, kinds=["road"], notch_width_m=width,
        bed_reach_m=50.0, max_depth_m=5.0, snap_radius_m=30.0, report=report,
    )  # fmt: skip
    # The reach is 50 m: the ends are ten pixels on each side of the crossing.
    for row in (ROAD5 - 10, ROAD5 + 10):
        assert (out[row, :] == dem[row, :]).all()
    if width == 10.0:
        moved = np.argwhere(out < dem - 1e-4)
        assert set(moved[:, 0].tolist()) == {ROAD5 - 1, ROAD5, ROAD5 + 1}
        assert set(moved[:, 1].tolist()) == {AXIS5 - 1, AXIS5, AXIS5 + 1}
        assert report.pixels_lowered == 9
        # The bed is not a straight line, so a bank pixel takes the level of its own row.
        levels = [out[row, AXIS5 - 1] for row in (ROAD5 - 1, ROAD5, ROAD5 + 1)]
        assert out[ROAD5, AXIS5] == pytest.approx(out[ROAD5, AXIS5 + 1])
        assert len({round(float(level), 4) for level in levels}) == 3
        assert (out <= dem).all()
