"""Delineation of a MODFLOW 6 SFR reach network from flow-product rasters.

``delineate_sfr_reaches`` turns a stream-link raster + D8 pointer + accumulation +
DEM into an ordered, explicitly-connected reach table. The tests use a synthetic
Y-shaped network (two headwater tributaries converging into a main channel that
drains into a lake) and check:

* the reaches are numbered downstream-increasing (a reach has a smaller ifno than
  the reach it feeds);
* the signed connectivity is reciprocal (every downstream link lists its parent
  upstream);
* drainage area accumulates to the outlet;
* reach tops descend monotonically downstream after conditioning;
* the reach entering the lake is flagged terminal-to-lake;
* with no lake mask the same network simply leaves the model (no terminal flag).
"""

from __future__ import annotations

import numpy as np
import pytest
from affine import Affine

from hydromodpy.spatial.geographic.core.sfr_network import (
    SfrReachTrace,
    delineate_sfr_reaches,
)

# WhiteboxTools D8 codes used to wire the synthetic network.
_S, _SE, _SW = 4, 2, 8
_NONE = 0  # pit / no flow

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
_TRANSFORM = Affine(_RES, 0.0, 0.0, 0.0, -_RES, _NROW * _RES)


def _synthetic_network() -> dict[str, np.ndarray]:
    link = np.zeros((_NROW, _NCOL), dtype=int)
    d8 = np.zeros((_NROW, _NCOL), dtype=int)
    acc = np.zeros((_NROW, _NCOL), dtype=float)
    dem = np.full((_NROW, _NCOL), 20.0, dtype=float)
    strahler = np.zeros((_NROW, _NCOL), dtype=int)

    # Link 1 (left tributary)
    link[0, 0] = 1
    link[1, 0] = 1
    d8[0, 0] = _S  # (0,0) -> (1,0)
    d8[1, 0] = _SE  # (1,0) -> (2,1)  leaves link 1 into link 3
    acc[0, 0], acc[1, 0] = 1, 2
    dem[0, 0], dem[1, 0] = 10.0, 9.0
    strahler[0, 0], strahler[1, 0] = 1, 1

    # Link 2 (right tributary)
    link[0, 2] = 2
    link[1, 2] = 2
    d8[0, 2] = _S  # (0,2) -> (1,2)
    d8[1, 2] = _SW  # (1,2) -> (2,1)  leaves link 2 into link 3
    acc[0, 2], acc[1, 2] = 1, 2
    dem[0, 2], dem[1, 2] = 10.0, 9.0
    strahler[0, 2], strahler[1, 2] = 1, 1

    # Link 3 (main channel)
    link[2, 1] = 3
    link[3, 1] = 3
    link[4, 1] = 3
    d8[2, 1] = _S  # (2,1) -> (3,1)
    d8[3, 1] = _S  # (3,1) -> (4,1)
    d8[4, 1] = _S  # (4,1) -> (5,1)  enters the lake row
    acc[2, 1], acc[3, 1], acc[4, 1] = 5, 6, 7
    dem[2, 1], dem[3, 1], dem[4, 1] = 8.0, 7.0, 6.0
    strahler[2, 1], strahler[3, 1], strahler[4, 1] = 2, 2, 2

    return {"link": link, "d8": d8, "acc": acc, "dem": dem, "strahler": strahler}


def _delineate(lake: bool) -> SfrReachTrace:
    g = _synthetic_network()
    lake_mask = None
    if lake:
        lake_mask = np.zeros((_NROW, _NCOL), dtype=bool)
        lake_mask[5, :] = True
    return delineate_sfr_reaches(
        link_id=g["link"],
        d8=g["d8"],
        acc=g["acc"],
        dem=g["dem"],
        transform=_TRANSFORM,
        crs_wkt="EPSG:2154",
        dem_res_m=_RES,
        strahler=g["strahler"],
        lake_mask=lake_mask,
        min_slope=1e-4,
    )


def test_reaches_are_numbered_downstream_increasing() -> None:
    trace = _delineate(lake=True)
    assert trace.reach_count == 3
    by_ifno = {r.ifno: r for r in trace.reaches}
    # Every reach has a strictly smaller ifno than the reach it feeds.
    for reach in trace.reaches:
        for down in reach.downstream:
            assert reach.ifno < down
    # The main channel is the most-downstream reach (highest ifno, no downstream).
    main = max(trace.reaches, key=lambda r: r.ifno)
    assert main.downstream == ()
    assert len(by_ifno[main.ifno].upstream) == 2


def test_connectivity_is_reciprocal() -> None:
    trace = _delineate(lake=True)
    by_ifno = {r.ifno: r for r in trace.reaches}
    for reach in trace.reaches:
        for down in reach.downstream:
            assert reach.ifno in by_ifno[down].upstream
        for up in reach.upstream:
            assert reach.ifno in by_ifno[up].downstream


def test_drainage_area_accumulates_to_outlet() -> None:
    trace = _delineate(lake=True)
    main = max(trace.reaches, key=lambda r: r.ifno)
    # acc=7 cells at 100 m -> 7 * 0.01 km2.
    assert main.area_km2 == pytest.approx(0.07)
    assert main.strahler == 2


def test_reach_tops_descend_monotonically() -> None:
    trace = _delineate(lake=True)
    by_ifno = {r.ifno: r for r in trace.reaches}
    for reach in trace.reaches:
        for down in reach.downstream:
            assert by_ifno[down].rtp < reach.rtp
        assert reach.rgrd >= 1e-4


def test_terminal_reach_into_lake_is_flagged() -> None:
    trace = _delineate(lake=True)
    terminal = [r for r in trace.reaches if r.is_terminal_to_lake]
    assert len(terminal) == 1
    # The main channel (highest accumulation) is the one entering the lake.
    assert terminal[0].ifno == max(r.ifno for r in trace.reaches)
    assert terminal[0].downstream == ()


def test_no_lake_means_no_terminal_flag() -> None:
    trace = _delineate(lake=False)
    assert trace.reach_count == 3
    assert all(not r.is_terminal_to_lake for r in trace.reaches)
    # The main channel still leaves the model (no downstream reach).
    main = max(trace.reaches, key=lambda r: r.ifno)
    assert main.downstream == ()


def test_link_crossing_the_lake_is_truncated_at_the_shoreline() -> None:
    # The main channel CROSSES the lake (its raster path continues through and
    # past the footprint): the reach must stop at the shoreline, flag terminal,
    # and the through-lake cells must not become reaches.
    g = _synthetic_network()
    lake_mask = np.zeros((_NROW, _NCOL), dtype=bool)
    lake_mask[3, :] = True  # the lake straddles the MIDDLE of link 3
    trace = delineate_sfr_reaches(
        link_id=g["link"],
        d8=g["d8"],
        acc=g["acc"],
        dem=g["dem"],
        transform=_TRANSFORM,
        crs_wkt="EPSG:2154",
        dem_res_m=_RES,
        strahler=g["strahler"],
        lake_mask=lake_mask,
        min_slope=1e-4,
    )
    terminal = [r for r in trace.reaches if r.is_terminal_to_lake]
    assert len(terminal) == 1
    # The truncated main channel keeps only its pre-lake cell (2,1): one
    # cell-to-cell step of geometry, no downstream connection.
    assert terminal[0].downstream == ()
    assert terminal[0].rlen == pytest.approx(_RES)
    # No reach geometry enters the lake row (y of row 3 spans [200, 300]).
    for reach in trace.reaches:
        for _, y in reach.line.coords:
            assert y >= 250.0


def test_boolean_mask_tags_the_single_lake_as_lake_one() -> None:
    # A plain boolean mask (legacy single-lake path) reads as lake 1: the
    # terminal reach is tagged terminal_lake == 1 so the builder routes it to the
    # first lake (== the network outflow_to_lake = 1).
    trace = _delineate(lake=True)
    terminal = [r for r in trace.reaches if r.is_terminal_to_lake]
    assert len(terminal) == 1
    assert terminal[0].terminal_lake == 1
    # Non-terminal reaches carry no lake tag.
    assert all(r.terminal_lake is None for r in trace.reaches if not r.is_terminal_to_lake)


def _two_stream_two_lake() -> dict[str, np.ndarray]:
    # 3x3 grid: stream L1 drains south into lake 1 (cell 2,0), stream L2 drains
    # south into lake 2 (cell 2,2). The labeled mask tags each terminal reach with
    # the specific lake it feeds.
    nrow, ncol = 3, 3
    link = np.zeros((nrow, ncol), dtype=int)
    d8 = np.zeros((nrow, ncol), dtype=int)
    acc = np.zeros((nrow, ncol), dtype=float)
    dem = np.full((nrow, ncol), 20.0, dtype=float)
    for col in (0, 2):
        tag = 1 if col == 0 else 2
        link[0, col] = tag
        link[1, col] = tag
        d8[0, col] = _S  # (0,col) -> (1,col)
        d8[1, col] = _S  # (1,col) -> (2,col)  the lake cell
        acc[0, col], acc[1, col] = 1, 2
        dem[0, col], dem[1, col] = 10.0, 9.0
    label = np.zeros((nrow, ncol), dtype=np.int32)
    label[2, 0] = 1  # lake 1 (e.g. the pre-retenue)
    label[2, 2] = 2  # lake 2 (e.g. the main reservoir)
    return {"link": link, "d8": d8, "acc": acc, "dem": dem, "label": label}


def test_two_labeled_lakes_tag_distinct_terminals() -> None:
    g = _two_stream_two_lake()
    trace = delineate_sfr_reaches(
        link_id=g["link"],
        d8=g["d8"],
        acc=g["acc"],
        dem=g["dem"],
        transform=Affine(_RES, 0.0, 0.0, 0.0, -_RES, 3 * _RES),
        crs_wkt="EPSG:2154",
        dem_res_m=_RES,
        lake_mask=g["label"],
        min_slope=1e-4,
    )
    terminals = [r for r in trace.reaches if r.is_terminal_to_lake]
    assert len(terminals) == 2
    # The stream entering cell (2,0) is tagged lake 1, the one entering (2,2) lake 2.
    assert sorted(r.terminal_lake for r in terminals) == [1, 2]


def test_truncation_tags_the_lake_label() -> None:
    # A link crossing a LABELED lake (label 2) is truncated at the shoreline and
    # tagged terminal_lake == 2 (the label at the truncation cell), not just 1.
    g = _synthetic_network()
    label = np.zeros((_NROW, _NCOL), dtype=np.int32)
    label[3, :] = 2  # the lake straddling the middle of link 3 is lake 2
    trace = delineate_sfr_reaches(
        link_id=g["link"],
        d8=g["d8"],
        acc=g["acc"],
        dem=g["dem"],
        transform=_TRANSFORM,
        crs_wkt="EPSG:2154",
        dem_res_m=_RES,
        strahler=g["strahler"],
        lake_mask=label,
        min_slope=1e-4,
    )
    terminal = [r for r in trace.reaches if r.is_terminal_to_lake]
    assert len(terminal) == 1
    assert terminal[0].terminal_lake == 2
