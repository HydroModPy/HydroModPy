"""SFR PERIOD rows from the forcings of a network, flows in m3/s and rain in m/s.

Inflow lands on the headwater reaches by drainage area, runoff on every reach by length,
and rain and evaporation on every reach unscaled. A constant gives one row in period 0. A
series gives a row whenever its value changes, or one TS6 series when the mode asks for it.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.solver.modflow6.builders._sfr_period import (
    _forcing_targets,
    _ts6_series_name,
    build_sfr_period_data,
)
from hydromodpy.solver.modflow6.builders.sfr import ResolvedSfrNetwork, SfrReachRecord
from tests._helpers.model_factory import make_model

DAY_S = 86400.0


def reach(
    ifno: int,
    *,
    rlen: float = 10.0,
    area_km2: float = 0.0,
    is_headwater: bool = False,
    upstream: tuple[int, ...] = (),
) -> SfrReachRecord:
    return SfrReachRecord(
        ifno=ifno,
        cellid=(0, ifno),
        rlen=rlen,
        rwid=2.0,
        rgrd=1e-3,
        rtp=95.0,
        upstream=upstream,
        downstream=(),
        area_km2=area_km2,
        is_headwater=is_headwater,
    )


def network(reaches: tuple[SfrReachRecord, ...], **definition) -> ResolvedSfrNetwork:
    return ResolvedSfrNetwork(network_id="main", reaches=reaches, definition=definition)


def three_day_model(mode: str = "inline", nper: int = 3) -> SimpleNamespace:
    process = SimpleNamespace(lak_forcing_mode=mode, ts6_min_periods=120)
    return SimpleNamespace(
        inputs=make_model(),
        nper=nper,
        perlen=[DAY_S] * 3,
        modflow_config=SimpleNamespace(process_specific=process),
    )


TWO_HEADWATERS = (
    reach(0, area_km2=3.0, is_headwater=True),
    reach(1, area_km2=1.0, is_headwater=True),
)
UNFLAGGED_SOURCES = (reach(0), reach(1), reach(2, upstream=(0, 1)))
EVERY_REACH_FED = (reach(0, upstream=(1,)), reach(1, upstream=(0,)))

TARGETS = [
    pytest.param("inflow", TWO_HEADWATERS, {0: 0.75, 1: 0.25}, id="inflow by area"),
    # No flagged headwater, so the reaches with nothing upstream take it, equally without areas.
    pytest.param("inflow", UNFLAGGED_SOURCES, {0: 0.5, 1: 0.5}, id="inflow without areas"),
    pytest.param("inflow", EVERY_REACH_FED, {}, id="inflow without a source reach"),
    pytest.param(
        "runoff",
        (reach(0, rlen=30.0), reach(1, rlen=10.0)),
        {0: 0.75, 1: 0.25},
        id="runoff by length",
    ),
    pytest.param("runoff", (reach(0, rlen=0.0),), {}, id="runoff without length"),
    pytest.param("rainfall", (reach(0), reach(1)), {0: 1.0, 1: 1.0}, id="rain unscaled"),
]


@pytest.mark.parametrize(("keyword", "reaches", "targets"), TARGETS)
def test_forcing_targets(keyword, reaches, targets) -> None:
    assert _forcing_targets(keyword, reaches) == pytest.approx(targets)


def test_forcing_without_a_target_gives_no_row() -> None:
    net = network((reach(0, rlen=0.0),), runoff={"kind": "constant", "value": 1.0, "units": "m3/s"})

    rows, series = build_sfr_period_data(three_day_model(), network=net)

    assert (rows, series) == ({}, [])


def test_series_without_a_period_gives_no_row() -> None:
    forcing = {"kind": "values", "values": [1.0, 1.0, 2.0], "units": "m3/s"}
    net = network(TWO_HEADWATERS, headwater_inflow=forcing)

    assert build_sfr_period_data(three_day_model(nper=0), network=net) == ({}, [])


def test_series_gives_a_row_when_its_value_changes() -> None:
    forcing = {"kind": "values", "values": [1.0, 1.0, 2.0], "units": "m3/s"}
    net = network(TWO_HEADWATERS, headwater_inflow=forcing)

    rows, series = build_sfr_period_data(three_day_model(), network=net)

    # Reach 0 takes 3 / 4 of the inflow and reach 1 the rest. Period 1 repeats period 0.
    assert series == []
    assert rows == {
        0: [[0, "inflow", pytest.approx(0.75)], [1, "inflow", pytest.approx(0.25)]],
        2: [[0, "inflow", pytest.approx(1.5)], [1, "inflow", pytest.approx(0.5)]],
    }


def test_series_of_a_rate_is_one_ts6_series() -> None:
    forcing = {"kind": "values", "values": [1e-8, 2e-8, 3e-8], "units": "m/s"}
    net = network((reach(0), reach(1)), rainfall=forcing)

    rows, series = build_sfr_period_data(three_day_model(mode="ts6"), network=net)

    assert rows == {0: [[0, "rainfall", "sfr_rain"], [1, "rainfall", "sfr_rain"]]}
    [rain] = series
    assert rain.name == "sfr_rain"
    assert rain.times == (0.0, DAY_S, 2 * DAY_S, 3 * DAY_S)
    assert rain.values == pytest.approx(
        (1e-8, 2e-8, 3e-8, 3e-8)
    )  # the last value closes the series


def test_uneven_split_gives_one_ts6_series_per_reach() -> None:
    forcing = {"kind": "values", "values": [4.0, 8.0, 8.0], "units": "m3/s"}
    net = network(TWO_HEADWATERS, headwater_inflow=forcing)

    rows, series = build_sfr_period_data(three_day_model(mode="ts6"), network=net)

    assert rows == {0: [[0, "inflow", "sfr_in_0"], [1, "inflow", "sfr_in_1"]]}
    assert [s.name for s in series] == ["sfr_in_0", "sfr_in_1"]
    assert series[0].values == pytest.approx((3.0, 6.0, 6.0, 6.0))  # 3 / 4 of the inflow
    assert series[1].values == pytest.approx((1.0, 2.0, 2.0, 2.0))  # 1 / 4 of the inflow


SERIES_NAMES = [
    pytest.param("inflow", None, "sfr_in", id="inflow"),
    pytest.param("evaporation", 3, "sfr_evap_3", id="evaporation of reach 3"),
    pytest.param("seepage", None, "sfr_seep", id="unknown keyword, first four letters"),
    pytest.param("seepage", 12345678901, "sfr_seep_1234567", id="cut at 16 characters"),
]


@pytest.mark.parametrize(("keyword", "ifno", "name"), SERIES_NAMES)
def test_ts6_series_name(keyword, ifno, name) -> None:
    assert _ts6_series_name(keyword, ifno) == name
