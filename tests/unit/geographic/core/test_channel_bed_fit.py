"""The bed regularisation moves the channel pixels only, and leaves no rise along them.

A synthetic valley on a 25 m grid: a main stem down the middle column and a
tributary joining it from the west, both carrying a gentle bed plus a
symmetric noise larger than the drop between two pixels. The hillslopes stand
well above the bed and are not on the tree.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin, xy
from shapely.geometry import Point, box

from hydromodpy.spatial.geographic.core.channel_bed_fit import pixel_tree, regularize_channel_bed
from hydromodpy.spatial.geographic.core.ground_bed import (
    WINDOW_MARGIN_M,
    _domain_bounds,
    bed_dem_path,
    ground_bed_path,
    ground_bed_report_path,
    regularized_ground_from_config,
    restrict_to_window,
    top_dem_path_from_config,
)
from hydromodpy.spatial.geographic.core.ground_corrections import ground_dem_from_config
from tests._helpers import ground_bench as bench
from tests._helpers.geographic_cases import bench_project, write_features

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


# --- a straight channel: gaps and cuts ----------------------------------------
#
# A straight channel down the middle column of a 25 m grid. The gap case puts a
# capped embankment on the bed; the weir case is the reach of a weir with a 2 m
# drop and an undeclared bump below its foot; the dam case is a pond held by a
# crest 10 m above it.

MID = 1


def _column(values: list[float]):
    rows = len(values)
    transform = from_origin(0.0, rows * RES, RES, RES)
    top = np.full((rows, 3), 200.0, dtype="float32")
    top[:, MID] = values
    channel = np.zeros((rows, 3), dtype=bool)
    channel[:, MID] = True
    d8 = np.full((rows, 3), SOUTH, dtype=int)
    d8[-1, :] = 0
    return top, channel, d8, transform


def _fit_column(top, channel, d8, transform, **kwargs):
    return regularize_channel_bed(
        top, valid=np.ones_like(channel), transform=transform, channel=channel, d8=d8, **kwargs
    )


def _point(transform, row: int, dx: float = 0.0) -> Point:
    x, y = xy(transform, row, MID)
    return Point(x + dx, y)


BED = [10.0 - 0.25 * i for i in range(11)]
EMBANKMENT = 5


def test_a_notch_footprint_pixel_is_a_gap_that_follows_its_measured_neighbours() -> None:
    values = list(BED)
    values[EMBANKMENT] += 1.5  # what the cap of the notch left of the embankment
    top, channel, d8, transform = _column(values)
    gap = np.zeros_like(channel)
    gap[EMBANKMENT, MID] = True

    as_bump, _ = _fit_column(top, channel, d8, transform)
    out, report = _fit_column(top, channel, d8, transform, gap=gap)

    assert as_bump[EMBANKMENT - 1, MID] > BED[EMBANKMENT - 1] + 0.4
    np.testing.assert_allclose(out[:, MID], BED, atol=1e-5)
    assert report.gap_pixels == 1
    assert (report.raised, report.lowered) == (0, 0)


# 0 (head) -> 1 -> 2 (weir crest) -> 3 (foot) -> 4 (bump) -> 5 (root).
WEIR_REACH = [12.5, 12.2, 12.0, 10.0, 15.0, 9.0]
WEIR = 2


def _weirs(transform, *, dx: float = 0.0):
    return [("weir", "moulin", 2.0, _point(transform, WEIR, dx))]


def test_a_declared_weir_keeps_the_reach_above_its_drop() -> None:
    top, channel, d8, transform = _column(WEIR_REACH)

    uncut, _ = _fit_column(top, channel, d8, transform)
    out, report = _fit_column(top, channel, d8, transform, barriers=_weirs(transform))

    assert uncut[WEIR, MID] > WEIR_REACH[WEIR] + 0.1
    np.testing.assert_allclose(out[: WEIR + 1, MID], WEIR_REACH[: WEIR + 1])
    assert report.climbs_at_cuts == 1
    assert report.violations_after == 0
    (cut,) = report.cuts
    assert (cut["kind"], cut["name"], cut["drop_m"]) == ("weir", "moulin", 2.0)
    # The foot is pooled with the bump and tilted about their mean.
    assert cut["climb_m"] == pytest.approx(12.5 + 1.0e-4 * RES / 2 - 12.0, abs=1e-4)


@pytest.mark.parametrize(
    ("dx", "lake", "cuts", "skipped"),
    [
        (20.0, False, 1, {}),
        (40.0, False, 0, {"off_channel": 1}),
        (0.0, True, 0, {"in_lake": 1}),
    ],
    ids=["snapped within the radius", "beyond the radius", "inside a declared lake"],
)
def test_a_weir_cuts_only_on_the_channel_and_outside_a_lake(dx, lake, cuts, skipped) -> None:
    top, channel, d8, transform = _column(WEIR_REACH)
    rows = len(WEIR_REACH)
    lakes = [box(0.0, (rows - WEIR - 2) * RES, 3 * RES, (rows - WEIR) * RES)] if lake else []

    out, report = _fit_column(
        top, channel, d8, transform, barriers=_weirs(transform, dx=dx), lakes=lakes
    )

    assert len(report.cuts) == cuts
    assert report.barriers_skipped == skipped
    if cuts:
        np.testing.assert_allclose(out[: WEIR + 1, MID], WEIR_REACH[: WEIR + 1])
    elif lake:
        assert report.lake_pixels == 2
        np.testing.assert_array_equal(out[WEIR : WEIR + 2, MID], top[WEIR : WEIR + 2, MID])
    else:
        assert out[WEIR, MID] > WEIR_REACH[WEIR] + 0.1


def test_two_barriers_on_one_pixel_cut_it_once_and_say_so() -> None:
    top, channel, d8, transform = _column(WEIR_REACH)
    barriers = _weirs(transform) + [("dam", "", float("nan"), _point(transform, WEIR, 5.0))]

    _, report = _fit_column(top, channel, d8, transform, barriers=barriers)

    assert len(report.cuts) == 1
    assert report.barriers_skipped == {"same_pixel": 1}


POND = CREST = 40
POND_LEVEL, CREST_LEVEL, VALLEY = 300.0, 310.0, 280.0
DAM_REACH = [POND_LEVEL] * POND + [CREST_LEVEL] + [VALLEY - 0.1 * i for i in range(10)]


@pytest.mark.parametrize("snapped", [CREST, CREST - 1], ids=["crest", "pond-side foot"])
def test_a_dam_snapped_to_its_crest_or_its_foot_leaves_the_pond_untouched(snapped) -> None:
    top, channel, d8, transform = _column(DAM_REACH)
    dam = [("dam", "barrage", 10.0, _point(transform, snapped))]

    uncut, _ = _fit_column(top, channel, d8, transform)
    out, report = _fit_column(top, channel, d8, transform, barriers=dam)

    assert uncut[: POND - 1, MID].mean() > POND_LEVEL + 0.2
    # The pond above the snapped pixel is a tree of its own, tilted about its level.
    pond = out[:snapped, MID].astype(float)
    np.testing.assert_allclose(pond.mean(), POND_LEVEL, atol=1e-4)
    assert pond.max() - pond.min() <= 1.0e-4 * RES * (snapped - 1) + 1e-4
    np.testing.assert_array_equal(out[snapped : CREST + 1, MID], top[snapped : CREST + 1, MID])
    assert len(report.cuts) == 1


LAKE_ROWS = slice(5, 15)
LAKE_REACH = (
    [306.0, 305.0, 305.4, 304.0, 303.0] + [300.0] * 10 + [299.0, 298.0, 298.6, 297.0, 296.0]
)


def test_a_declared_lake_keeps_its_surface_and_cuts_the_tree() -> None:
    top, channel, d8, transform = _column(LAKE_REACH)
    rows = len(LAKE_REACH)
    lake = box(0.0, (rows - LAKE_ROWS.stop) * RES, 3 * RES, (rows - LAKE_ROWS.start) * RES)

    out, report = _fit_column(top, channel, d8, transform, lakes=[lake])

    np.testing.assert_array_equal(out[LAKE_ROWS, MID], top[LAKE_ROWS, MID])
    assert report.lake_pixels == 10
    assert report.channel_pixels == rows - 10
    for reach in (slice(0, LAKE_ROWS.start), slice(LAKE_ROWS.stop, rows)):
        assert (np.diff(out[reach, MID].astype(float)) < 0).all()
    assert report.rises_after_fit == 0


def test_a_tree_with_no_channel_pixel_leaves_the_top_alone() -> None:
    top, channel, d8, transform = _column(BED)

    out, report = _fit_column(top, np.zeros_like(channel), d8, transform)

    np.testing.assert_array_equal(out, top)
    assert report.channel_pixels == 0


# --- the domain window --------------------------------------------------------

GRID = from_origin(0.0, 10_000.0, 10.0, 10.0)  # 1000 x 1000 pixels of 10 m


@pytest.mark.parametrize(
    ("bounds", "margin", "kept"),
    [
        ((4000.0, 4000.0, 5000.0, 5000.0), 0.0, 100 * 100),
        ((4000.0, 4000.0, 5000.0, 5000.0), 100.0, 120 * 120),
        ((50_000.0, 0.0, 60_000.0, 1000.0), 0.0, 0),
    ],
    ids=["inside", "margin widens", "off the grid"],
)
def test_the_bed_fit_reads_the_channel_inside_the_domain_window(bounds, margin, kept) -> None:
    channel = np.ones((1000, 1000), dtype=bool)

    window = restrict_to_window(channel, GRID, bounds, margin_m=margin)

    assert window.sum() == kept
    assert bool(window[500, 450]) is (kept > 0)  # inside the domain bounds
    assert not window[0, 0]
    assert channel.all()  # the input is left alone
    assert WINDOW_MARGIN_M > 0


@pytest.mark.parametrize("buffered", [True, False])
def test_the_window_covers_the_buffered_domain_else_the_watershed(tmp_path, buffered) -> None:
    watershed = write_features(tmp_path / "watershed.shp", [box(4000, 4000, 5000, 5000)])
    box_buff = None
    if buffered:
        box_buff = write_features(tmp_path / "box_buff.shp", [box(500, 500, 8500, 8500)])
    paths = SimpleNamespace(
        watershed_shp=str(watershed), box_buff=box_buff, geographic_path=str(tmp_path)
    )

    bounds = _domain_bounds(SimpleNamespace(paths=paths))

    assert bounds == ((500.0,) * 2 + (8500.0,) * 2 if buffered else (4000.0,) * 2 + (5000.0,) * 2)


# --- the fit read from the config and written next to the ground -------------


def _read(path) -> np.ndarray:
    with rasterio.open(path) as src:
        return src.read(1)


def test_the_regularised_ground_differs_from_the_notched_ground_on_the_channel_only(
    tmp_path,
) -> None:
    weir = Point(bench.x_of(bench.AXIS), bench.y_of(4))
    crossings = bench.structures(("road", bench.road_along(10)), ("weir", weir))
    crossings["name"] = ["", "moulin"]
    crossings["drop_m"] = [float("nan"), 1.0]
    project = bench_project(tmp_path, crossings)
    config, setup = project.config, project.setup
    ground = ground_dem_from_config(config, setup, channel=project.channel)
    watershed = write_features(tmp_path / "watershed.shp", [box(0, 0, 210, 210)])
    setup.paths.watershed_shp = str(watershed)

    out = regularized_ground_from_config(
        config, setup, d8_tif=project.d8, river_products=SimpleNamespace()
    )

    assert out == ground_bed_path(setup)
    assert top_dem_path_from_config(config, setup) == str(out)
    fitted, notched = _read(out), _read(ground)
    off_channel = ~project.valley.streams
    np.testing.assert_array_equal(fitted[off_channel], notched[off_channel])
    document = json.loads(ground_bed_report_path(setup).read_text(encoding="utf-8"))
    assert document["parameters"]["notch_footprint"] is True
    assert document["parameters"]["window_margin_m"] == WINDOW_MARGIN_M
    assert [cut["name"] for cut in document["cuts"]] == ["moulin"]
    assert document["channel_pixels"] == bench.N
    config.bed_regularization.enabled = False
    assert top_dem_path_from_config(config, setup) == str(ground)
    assert bed_dem_path(Path("geo") / "clip.tif") == Path("geo") / "clip_bed.tif"


def _misaligned(project, tmp_path):
    from tests._helpers.geotiffs import write_geotiff

    project.d8 = write_geotiff(
        tmp_path / "shifted.tif", project.valley.d8, origin=(3.0, 210.0), cell=10.0
    )


def _coarse(project, tmp_path):
    from tests._helpers.geotiffs import write_geotiff

    project.d8 = write_geotiff(tmp_path / "coarse.tif", project.valley.d8[::2, ::2], cell=20.0)


def _no_kind(project, tmp_path):
    write_features(tmp_path / "plain.gpkg", [Point(0, 0)])
    project.config.crossings.path = tmp_path / "plain.gpkg"


def _no_crs(project, tmp_path):
    write_features(tmp_path / "bare.gpkg", [Point(0, 0)], crs=None, kind=["weir"])
    project.config.crossings.path = tmp_path / "bare.gpkg"


def _no_channel(project, tmp_path):
    Path(project.channel.streams_tif).unlink()


@pytest.mark.parametrize(
    ("spoil", "error", "reason"),
    [
        (_misaligned, ValueError, "not aligned with the pixels"),
        (_coarse, ValueError, "another cell size"),
        (_no_kind, ValueError, "no 'kind' column"),
        (_no_crs, ValueError, "carries no CRS"),
        (_no_channel, FileNotFoundError, "reads the channel tree"),
        (
            lambda p, t: setattr(p.config.crossings, "path", t / "gone.gpkg"),
            FileNotFoundError,
            "points to nothing",
        ),
    ],
    ids=["misaligned raster", "other cell size", "no kind", "no crs", "no channel", "no file"],
)
@pytest.mark.filterwarnings("ignore:'crs' was not provided")
def test_an_input_the_fit_cannot_place_on_the_ground_is_refused(
    tmp_path, spoil, error, reason
) -> None:
    project = bench_project(tmp_path, None)
    project.config.crossings.enabled = False
    spoil(project, tmp_path)

    with pytest.raises(error, match=reason):
        regularized_ground_from_config(
            project.config, project.setup, d8_tif=project.d8, river_products=None
        )


def test_without_a_crossings_file_no_barrier_cuts_the_tree(tmp_path) -> None:
    project = bench_project(tmp_path, None, prune=True)
    project.config.crossings.enabled = False
    link = bench.write_raster(tmp_path / "link.tif", project.valley.streams.astype("float32"))

    regularized_ground_from_config(
        project.config,
        project.setup,
        d8_tif=project.d8,
        river_products=SimpleNamespace(stream_link_id_full_tif=str(link)),
    )

    document = json.loads(ground_bed_report_path(project.setup).read_text(encoding="utf-8"))
    assert document["cuts"] == []
    assert document["parameters"]["crossings_path"] is None
    assert document["parameters"]["channel_raster"] == str(link)
    assert document["parameters"]["window_margin_m"] is None
