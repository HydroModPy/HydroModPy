"""Unit conversion of well, recharge and ETP payloads in `Flow` (m3/day to m3/s, mm/day to m/s).

A payload declares one `units` and the flow converts its numbers to SI on the way in, including
the first-period override `first_clim` and the loaded sources scaled by `factor`.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import xarray as xr
from pydantic import ValidationError

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.model.boundaries.climate import apply_recharge_load_result_to_flow
from hydromodpy.model.flow import Flow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig
from hydromodpy.model.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig

_MM_PER_DAY_IN_M_PER_S = 1e-3 / 86400.0
CELL = {"kind": "cell", "cell": [0, 0, 0]}


def _normalized(recharge: FlowRechargeConfig) -> FlowRechargeConfig:
    return Flow._normalize_recharge_config(recharge, location_prefix="flow.sinks_sources.recharge")


def _flow(**sections) -> Flow:
    return Flow(FlowConfig(sinks_sources=FlowSinksSourcesConfig(**sections)))


WELL_FLUXES = [
    pytest.param(-86400.0, -1.0, id="scalar"),  # 86400 m3/day is 1 m3/s
    pytest.param([-86400.0, -43200.0], [-1.0, -0.5], id="list"),
]


@pytest.mark.parametrize(("flux", "expected_m3_s"), WELL_FLUXES)
def test_well_flux_in_m3_s(flux, expected_m3_s):
    flow = _flow(wells={"W1": {"location": CELL, "flux": flux, "units": "m3/day"}})

    well = flow.sinks_sources["wells"]["W1"]
    assert well.units == "m3/s"
    assert well.flux == pytest.approx(expected_m3_s)


def test_well_forcing_without_flux():
    forcing = {"kind": "constant", "value": -100.0}
    flow = _flow(wells={"W1": {"location": CELL, "units": "m3/day", "forcing": forcing}})

    well = flow.sinks_sources["wells"]["W1"]
    assert well.flux is None
    assert well.units == "m3/s"
    assert well.forcing.units == "m3/day"


# Rates in mm/day, the expected values in m/s.
RATE_PAYLOADS = [
    pytest.param(
        "recharge", {"values": 3.0, "units": "mm/day"}, 3.0 * _MM_PER_DAY_IN_M_PER_S, id="recharge"
    ),
    pytest.param(
        "recharge",
        {"values": {0: 3.0, 1: 6.0}, "units": "mm/day"},
        {0: 3.0 * _MM_PER_DAY_IN_M_PER_S, 1: 6.0 * _MM_PER_DAY_IN_M_PER_S},
        id="recharge by period",
    ),
    pytest.param(
        "recharge",
        {"values": [1.0, -2.0], "units": "mm/day", "negative_to_evt": True},
        [1.0 * _MM_PER_DAY_IN_M_PER_S, -2.0 * _MM_PER_DAY_IN_M_PER_S],
        id="negative recharge routed to evt",
    ),
    pytest.param(
        "etp",
        {"values": {0: 2.0, 1: 4.0}, "units": "mm/day"},
        {0: 2.0 * _MM_PER_DAY_IN_M_PER_S, 1: 4.0 * _MM_PER_DAY_IN_M_PER_S},
        id="etp by period",
    ),
]


@pytest.mark.parametrize(("section", "payload", "expected_m_s"), RATE_PAYLOADS)
def test_rate_in_m_s(section, payload, expected_m_s):
    rate = _flow(**{section: payload}).sinks_sources[section]

    assert rate.units == "m/s"
    assert rate.values == pytest.approx(expected_m_s)


def test_first_period_follows_the_payload_unit():
    normalized = _normalized(FlowRechargeConfig(values=[1.0, 2.0], first_clim=2.0, units="mm/day"))

    assert normalized.units == "m/s"
    assert normalized.first_clim == pytest.approx(2.0 * _MM_PER_DAY_IN_M_PER_S)


def test_si_payload_is_unchanged():
    normalized = _normalized(
        FlowRechargeConfig(values=[1e-8, 2e-8], first_clim=1.5e-8, units="m/s")
    )

    assert normalized.first_clim == pytest.approx(1.5e-8)


UNIT_REFUSALS = [
    pytest.param(
        {"wells": {"W1": {"location": CELL, "flux": -100.0, "units": "foo/day"}}},
        "flow.sinks_sources.wells.W1.units must be compatible with m3/s",
        id="unknown well units",
    ),
    pytest.param(
        {"recharge": {"values": -1.0, "units": "mm/day", "negative_to_evt": False}},
        "flow.sinks_sources.recharge.values must be non-negative",
        id="negative recharge",
    ),
    pytest.param(
        {"etp": {"values": -1.0, "units": "mm/day"}},
        "flow.sinks_sources.etp.values must be non-negative",
        id="negative etp",
    ),
]


@pytest.mark.parametrize(("sections", "match"), UNIT_REFUSALS)
def test_refusals(sections, match):
    with pytest.raises(ValueError, match=match):
        _flow(**sections)


# The factor on the recharge in force, from `values` and from `[data.recharge]`.
_DAYS = pd.date_range("2000-01-01", periods=2)
_RATES = [0.1, 1.0 / 3.0]


def _station() -> LoadResult:
    record = PointRecord(
        station_id="a",
        variable="recharge",
        source="sim2",
        unit="mm/day",
        frequency="D",
        data=pd.DataFrame({"datetime": _DAYS, "value": _RATES}),
        date_start=_DAYS[0].to_pydatetime(),
        date_end=_DAYS[1].to_pydatetime(),
    )
    return LoadResult(points=[record])


def _grid() -> LoadResult:
    frames = np.asarray(_RATES).reshape(2, 1, 1)
    data = xr.Dataset(
        {"recharge": (("time", "y", "x"), np.tile(frames, (1, 2, 2)))},
        coords={"time": _DAYS, "y": [0.0, 1.0], "x": [0.0, 1.0]},
        attrs={"crs": "EPSG:2154"},
    )
    record = FieldRecord(
        variable="recharge",
        source="sim2",
        unit="mm/day",
        data=data,
        bbox=(0.0, 0.0, 1.0, 1.0),
        crs="EPSG:2154",
        date_start=_DAYS[0].to_pydatetime(),
        date_end=_DAYS[1].to_pydatetime(),
        frequency="D",
    )
    return LoadResult(fields=[record])


def _bound(source: LoadResult, factor: float) -> FlowRechargeConfig:
    """Bind a source to a flow that declares ``factor``, and normalize as the flow does."""
    seen: list[FlowRechargeConfig] = []
    recharge = FlowRechargeConfig(factor=factor)
    flow = SimpleNamespace(
        active_sinks_sources=["recharge"],
        sinks_sources={},
        config=SimpleNamespace(sinks_sources=SimpleNamespace(recharge=recharge)),
        set_recharge=lambda config: seen.append(_normalized(config)),
    )
    assert apply_recharge_load_result_to_flow(flow=flow, recharge_result=source)
    return seen[0]


def test_factor_scales_a_loaded_source() -> None:
    station, grid = _station(), _grid()

    series = _bound(station, 2.0).values
    scaled = _bound(grid, 2.0).heterogeneous_source.fields[0].dataset

    assert series.tolist() == pytest.approx([2.0 * r * _MM_PER_DAY_IN_M_PER_S for r in _RATES])
    assert station.points[0].data["value"].tolist() == _RATES
    assert scaled["recharge"].values[:, 0, 0].tolist() == [0.2, 2.0 / 3.0]
    assert scaled.attrs == {"crs": "EPSG:2154"}
    assert grid.fields[0].dataset["recharge"].values[:, 0, 0].tolist() == _RATES


def test_factor_one_moves_nothing() -> None:
    rates = {"values": _RATES, "first_clim": 0.7, "units": "mm/day"}
    plain = _normalized(FlowRechargeConfig(**rates))
    unit = _normalized(FlowRechargeConfig(**rates, factor=1.0))
    assert (plain.values, plain.first_clim) == (unit.values, unit.first_clim)

    station = _normalized(FlowRechargeConfig(values=_RATES, units="mm/day")).values
    assert np.asarray(_bound(_station(), 1.0).values).tolist() == station
    grid = _grid()
    assert _bound(grid, 1.0).heterogeneous_source is grid


@pytest.mark.parametrize(
    ("written", "said"),
    [
        ({"factor": 0.0}, "greater than 0"),
        ({"factor": 2.0, "soil": SoilReservoirConfig(ru=100.0)}, "no rate to multiply"),
    ],
)
def test_factor_refusals(written, said) -> None:
    with pytest.raises(ValidationError, match=said):
        FlowRechargeConfig(**written)


@pytest.mark.parametrize(
    ("written", "peak"),
    [
        ({"factor": 3.0, "values": 2.0}, 6.0),
        ({"factor": 2.0, "values": {0: 1e-8, 1: -3e-8}, "units": "m/s"}, 6e-8 * 86400e3),
    ],
)
def test_peak_rate(written, peak) -> None:
    assert FlowRechargeConfig(**written).peak_rate_mm_day() == pytest.approx(peak)
