"""Delineation of a MODFLOW 6 SFR reach network from flow-product rasters.

A reach top is the model top at the reach outlet cell, read as is: the trace
lowers nothing (the bed profile is fitted later, on the solver side).
"""

from functools import partial
from pathlib import Path

import numpy as np
import pytest
from affine import Affine
from shapely.geometry import box

from hydromodpy.catchment.algorithms.sfr_network import (
    SfrReachTrace,
    build_sfr_reach_trace_from_products,
    delineate_sfr_reaches,
)
from tests._helpers.geotiffs import write_geotiff

# WhiteboxTools D8 codes, clockwise from the north-east: 1 NE, 2 E, 4 SE, 8 S,
# 16 SW, 32 W, 64 NW, 128 N. NOT the ESRI table, the same octants rotated by one.
_S, _SE, _SW = 8, 4, 16

# 6 rows x 3 cols. Two tributaries (links 1, 2) join the main channel (link 3),
# which drains south into the lake row (row 5).
#   (0,0)L1   .       (0,2)L2
#   (1,0)L1   .       (1,2)L2
#   .         (2,1)L3 .
#   .         (3,1)L3 .
#   .         (4,1)L3 .
#   lake      lake    lake
_RES = 100.0
_NROW, _NCOL = 6, 3


def _grid(nrow: int = _NROW, ncol: int = _NCOL) -> dict[str, np.ndarray]:
    return {
        "link_id": np.zeros((nrow, ncol), dtype=int),
        "d8": np.zeros((nrow, ncol), dtype=int),
        "acc": np.zeros((nrow, ncol), dtype=float),
        "top_dem": np.full((nrow, ncol), 20.0, dtype=float),
    }


def _y_network() -> dict[str, np.ndarray]:
    g = _grid()
    g["strahler"] = np.zeros((_NROW, _NCOL), dtype=int)
    for col, last in ((0, _SE), (2, _SW)):  # links 1 and 2, then into link 3
        g["link_id"][0:2, col] = 1 if col == 0 else 2
        g["d8"][0, col], g["d8"][1, col] = _S, last
        g["acc"][0:2, col] = (1, 2)
        g["top_dem"][0:2, col] = (10.0, 9.0)
        g["strahler"][0:2, col] = 1
    g["link_id"][2:5, 1] = 3
    g["d8"][2:5, 1] = _S  # (4,1) enters the lake row
    g["acc"][2:5, 1] = (5, 6, 7)
    g["top_dem"][2:5, 1] = (8.0, 7.0, 6.0)
    g["strahler"][2:5, 1] = 2
    return g


def _lake_rows(*rows: int, label: int | bool = True, nrow: int = _NROW) -> np.ndarray:
    mask = np.zeros((nrow, _NCOL), dtype=type(label))
    mask[list(rows), :] = label
    return mask


def _trace(g: dict[str, np.ndarray], **options) -> SfrReachTrace:
    nrow = g["link_id"].shape[0]
    return delineate_sfr_reaches(
        **g,
        transform=Affine(_RES, 0.0, 0.0, 0.0, -_RES, nrow * _RES),
        crs_wkt="EPSG:2154",
        dem_res_m=_RES,
        **{"min_slope": 1e-4, **options},
    )


def _main(trace: SfrReachTrace):
    return max(trace.reaches, key=lambda r: r.ifno)


def _terminals(trace: SfrReachTrace) -> list:
    return [r for r in trace.reaches if r.is_terminal_to_lake]


def test_reaches_are_numbered_downstream_connected_both_ways_and_topped_at_their_outlet() -> None:
    trace = _trace(_y_network(), lake_mask=_lake_rows(5))
    by_ifno = {r.ifno: r for r in trace.reaches}
    assert trace.reach_count == 3
    for reach in trace.reaches:
        for down in reach.downstream:
            assert reach.ifno < down
            assert reach.ifno in by_ifno[down].upstream
        for up in reach.upstream:
            assert reach.ifno in by_ifno[up].downstream
    main = _main(trace)
    assert main.downstream == ()
    assert len(main.upstream) == 2
    # acc = 7 cells at 100 m -> 7 * 0.01 km2.
    assert main.area_km2 == pytest.approx(0.07)
    assert main.strahler == 2
    assert main.rtp == pytest.approx(6.0)
    for reach in trace.reaches:
        if reach is not main:
            assert reach.rtp == pytest.approx(9.0)
        assert reach.rgrd >= 1e-4


def test_the_trace_never_lowers_a_reach_and_a_top_rising_downstream_keeps_a_floor() -> None:
    # The main outlet sits above both tributary outlets; a one-way pass would cut it to 9 m.
    # The routing DEM is breached, the model top is not: the gradient falls back
    # on the declared floor instead of going negative and breaking Manning.
    above, rising = _y_network(), _y_network()
    above["top_dem"][4, 1] = 12.0
    rising["top_dem"][2:5, 1] = (6.0, 7.0, 8.0)
    assert _main(_trace(above)).rtp == pytest.approx(12.0)
    assert all(reach.rgrd >= 1e-3 for reach in _trace(rising, min_slope=1e-3).reaches)


@pytest.mark.parametrize("label", [True, 2], ids=["boolean", "labelled lake 2"])
def test_a_link_crossing_the_lake_stops_at_the_shoreline(label) -> None:
    trace = _trace(_y_network(), lake_mask=_lake_rows(3, label=label))
    (terminal,) = _terminals(trace)
    assert terminal.terminal_lake == int(label)
    # The truncated main channel keeps its pre-lake cell (2,1): one step, no downstream.
    assert terminal.downstream == ()
    assert terminal.rlen == pytest.approx(_RES)
    assert all(y >= 250.0 for _, y in terminal.line.coords)
    # The channel below the dam is kept as its own reach, fed from the dam (REL-1).
    below = [r for r in trace.reaches if not r.is_terminal_to_lake and r.line.coords[0][1] < 200.0]
    assert len(below) == 1


def test_the_link_below_the_dam_is_kept_after_the_cut_at_the_lake() -> None:
    nrow = 8
    g = _grid(nrow)
    g["link_id"][:, 1] = 1
    g["d8"][: nrow - 1, 1] = _S
    g["acc"][:, 1] = np.arange(1, nrow + 1)
    g["top_dem"][:, 1] = 20.0 - np.arange(nrow)
    trace = _trace(g, lake_mask=_lake_rows(2, 3, nrow=nrow))
    above, below = sorted(trace.reaches, key=lambda r: r.ifno)
    assert above.is_terminal_to_lake
    assert not below.is_terminal_to_lake
    assert below.downstream == ()


def _column(*links: int) -> dict[str, np.ndarray]:
    """A single column draining south, with the given link id on each of its rows."""
    g = _grid()
    for row, link in enumerate(links):
        g["link_id"][row, 1] = link
        g["d8"][row, 1] = _S
        g["acc"][row, 1] = row + 1
        g["top_dem"][row, 1] = 10.0 - row
    return g


def test_a_link_gap_is_bridged_by_the_d8_path() -> None:
    # A WBT link raster can drop a cell between two links: following the pointer
    # reunites link 1 with link 2 instead of a spurious mid-catchment outlet.
    trace = _trace(_column(1, 1, 0, 2, 2), lake_mask=_lake_rows(5))
    upstream = min(trace.reaches, key=lambda r: r.ifno)
    assert trace.reach_count == 2
    assert upstream.downstream != ()
    assert not upstream.is_terminal_to_lake
    assert len(_terminals(trace)) == 1


@pytest.mark.parametrize(
    ("links", "pit", "lake", "terminal"),
    [((1, 1, 0, 0, 0), None, _lake_rows(4, label=3), 3), ((1, 1), 1, _lake_rows(5, label=1), None)],
    ids=["a gap short of the lake is bridged to it", "a bare outlet is left to the solver"],
)
def test_a_lone_reach_is_terminal_only_when_its_path_reaches_the_lake(links, pit, lake, terminal):
    # A path that pits without reaching a link or lake is left unflagged: the
    # solver mover builder decides its fate where the lake cells are known.
    g = _column(*links)
    if pit is not None:
        g["d8"][pit, 1] = 0
    (reach,) = _trace(g, lake_mask=lake).reaches
    assert (reach.is_terminal_to_lake, reach.terminal_lake) == (terminal is not None, terminal)


def test_a_one_cell_link_is_drawn_one_cell_long() -> None:
    g = _column(1, 2, 2)
    g["d8"][2, 1] = 0
    reaches = sorted(_trace(g).reaches, key=lambda r: r.ifno)
    assert [round(r.rlen) for r in reaches] == [100, 100]


def test_the_bed_elevation_is_read_on_the_top_dem_alone() -> None:
    # Lowering the top under the network by 10 m moves each reach top by 10 m
    # and nothing else.
    g = _y_network()
    lowered = dict(g, top_dem=np.where(g["link_id"] > 0, g["top_dem"] - 10.0, g["top_dem"]))
    on_top, on_lowered = _trace(g), _trace(lowered)
    assert [r.downstream for r in on_top.reaches] == [r.downstream for r in on_lowered.reaches]
    for raw, low in zip(on_top.reaches, on_lowered.reaches, strict=True):
        assert low.ifno == raw.ifno
        assert low.rtp == pytest.approx(raw.rtp - 10.0)
        assert low.rgrd == pytest.approx(raw.rgrd)


def test_a_reach_shorter_than_the_minimum_is_pruned_and_its_neighbours_relinked() -> None:
    trace = _trace(_y_network(), lake_mask=_lake_rows(5), min_reach_length_m=150.0)
    (main,) = trace.reaches
    assert main.is_terminal_to_lake
    assert main.upstream == ()


def _grid_with_top(top: np.ndarray) -> dict[str, np.ndarray]:
    return dict(_y_network(), top_dem=top)


def _nodata_under_the_main_outlet() -> dict[str, np.ndarray]:
    g = _y_network()
    g["top_dem"][4, 1] = np.nan
    return g


@pytest.mark.parametrize(
    ("g", "reason"),
    [
        (_nodata_under_the_main_outlet(), "nodata model top"),
        (_grid_with_top(np.zeros((2, 2))), "share one grid shape"),
        (_grid(), "No stream cells"),
    ],
    ids=["nodata top under a reach", "shapes differ", "no stream cell"],
)
def test_a_network_that_cannot_be_traced_is_refused_by_name(g, reason) -> None:
    with pytest.raises(ValueError, match=reason):
        _trace(g)


_N = 8


def _write_products(tmp_path: Path, nodata=None, **overrides: np.ndarray) -> dict[str, str]:
    """A straight south-flowing stream in column 3, two links, a lake at the foot."""
    link = np.zeros((_N, _N))
    link[1:4, 3], link[4:7, 3] = 1.0, 2.0
    acc = np.ones((_N, _N))
    acc[:, 3] = 5.0 * np.arange(1, _N + 1)
    rasters = {
        "link": link,
        "d8": np.full((_N, _N), 8.0),
        "acc": acc,
        "dem": np.repeat(100.0 - np.arange(_N)[:, None], _N, axis=1),
        "strahler": np.where(link > 0, 1.0, 0.0),
        **overrides,
    }
    write = partial(write_geotiff, cell=10.0, crs="EPSG:32630", nodata=nodata)
    return {name: str(write(tmp_path / f"{name}.tif", data)) for name, data in rasters.items()}


def _from_products(paths: dict[str, str], **options) -> SfrReachTrace:
    return build_sfr_reach_trace_from_products(
        stream_link_id_full_tif=paths["link"],
        d8_pointer_tif=paths["d8"],
        flow_acc_cells_tif=paths["acc"],
        top_dem_tif=paths["dem"],
        dem_res_m=10.0,
        **options,
    )


def test_a_trace_from_the_products_flags_the_reach_draining_into_the_lake(tmp_path) -> None:
    paths = _write_products(tmp_path)
    # Row 7 (y in [0, 10]) around column 3 is lake: the link-2 outlet (6, 3) drains into it.
    lake = box(20.0, 0.0, 60.0, 12.0)
    trace = _from_products(
        paths, stream_order_strahler_full_tif=paths["strahler"], lake_polygons=[lake]
    )
    outside = _from_products(paths)
    first, second = trace.reaches
    assert (first.downstream, second.upstream) == ((1,), (0,))
    assert (first.is_terminal_to_lake, second.is_terminal_to_lake) == (False, True)
    assert second.rtp < first.rtp
    assert "32630" in trace.crs_wkt or "WGS 84" in trace.crs_wkt
    assert outside.reach_count == 2
    assert not any(reach.is_terminal_to_lake for reach in outside.reaches)


def test_the_watershed_keeps_only_its_own_links(tmp_path) -> None:
    upper_half = box(0.0, 40.0, 80.0, 80.0)
    trace = _from_products(_write_products(tmp_path), watershed_polygons=[upper_half])
    (reach,) = trace.reaches
    assert min(y for _, y in reach.line.coords) >= 40.0


def test_the_products_refuse_a_misaligned_raster_and_a_nodata_top(tmp_path) -> None:
    paths = _write_products(tmp_path)
    holed = np.repeat(100.0 - np.arange(_N)[:, None], _N, axis=1)
    holed[6, 3] = -9999.0  # the outlet of link 2
    shifted = str(write_geotiff(tmp_path / "shifted.tif", holed, origin=(500.0, 80.0), cell=10.0))
    with pytest.raises(ValueError, match="misaligned.*top_dem"):
        _from_products({**paths, "dem": shifted})
    with pytest.raises(ValueError, match="nodata model top"):
        _from_products(_write_products(tmp_path / "holed", nodata=-9999.0, dem=holed))
