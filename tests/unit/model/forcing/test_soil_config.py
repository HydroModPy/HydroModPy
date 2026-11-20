"""Soil reservoir config: ru (mm), transit_time (days) and the fractions, read from a TOML section.

ru and transit_time carry their unit as a string ("120 mm", "5 days") or as a bare number in
mm and days. Each bound has its own message, written for a hydrogeologist, not Pydantic's.
"""

from __future__ import annotations

import re

import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.forcing.soil_config import SoilReservoirConfig, steady_start_refusal
from hydromodpy.model.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig

RU_TEXT = (
    "ru = {} mm is outside 0 to 1000 mm, the range of a soil water capacity: "
    'ru is in mm, so write ru = 120 or ru = "120 mm".'
)
IMPERVIOUS_TEXT = (
    "impervious_fraction = {}: it is the sealed share of the area, a fraction "
    "from 0 up to, not including, 1: write 0.05 for 5 %, not 5, and 0.0 for a "
    "rural catchment."
)
BYPASS_TEXT = (
    "bypass_fraction = {}: it is the share of the rain that skips the soil, "
    "a fraction from 0 up to, not including, 1: write 0.1 for 10 %, not 10, "
    "and 0.0 unless the site shows preferential flow."
)
ALPHA_TEXT = (
    "alpha = {}: alpha is the share of ru above which the soil evaporates at the "
    "full rate kc x ETP, above 0 and at most 1. Write a value such as 0.45."
)
KC_TEXT = "kc = {}: kc scales the loaded ETP, between 0 and 2. Write 1.0 to take the ETP as loaded."
TRANSIT_TEXT = (
    "transit_time = {} days is outside 0 to 30 days: a longer delay would "
    "rebuild the slow groundwater memory MODFLOW computes itself. Write 0 to "
    "send the recharge the same day, or a few days."
)

REFUSALS = [
    pytest.param({"ru": -1.0}, RU_TEXT.format(-1), id="ru below range"),
    pytest.param({"ru": 1001.0}, RU_TEXT.format(1001), id="ru above range"),
    pytest.param({"alpha": 0.0}, ALPHA_TEXT.format(0), id="alpha zero"),
    pytest.param({"alpha": 1.5}, ALPHA_TEXT.format(1.5), id="alpha above one"),
    pytest.param({"kc": -0.1}, KC_TEXT.format(-0.1), id="kc negative"),
    pytest.param({"kc": 2.1}, KC_TEXT.format(2.1), id="kc above two"),
    pytest.param(
        {"impervious_fraction": -0.1}, IMPERVIOUS_TEXT.format(-0.1), id="impervious negative"
    ),
    pytest.param({"impervious_fraction": 1.0}, IMPERVIOUS_TEXT.format(1), id="impervious one"),
    pytest.param({"bypass_fraction": -0.1}, BYPASS_TEXT.format(-0.1), id="bypass negative"),
    pytest.param({"bypass_fraction": 1.0}, BYPASS_TEXT.format(1), id="bypass one"),
    pytest.param({"transit_time": -1.0}, TRANSIT_TEXT.format(-1), id="transit time negative"),
    pytest.param({"transit_time": 31.0}, TRANSIT_TEXT.format(31), id="transit time above range"),
    pytest.param(
        {"spinup": "permanent"},
        "spinup = 'permanent': write \"first_year\" to repeat the first year of the "
        'run until the soil storage settles, or "none" to start from a full soil.',
        id="unknown spinup word",
    ),
    pytest.param(
        {"ru": "150"},
        'ru = "150" has no unit: write ru = 150 (a bare number is in mm) or ru = "150 mm".',
        id="ru string without unit",
    ),
    pytest.param(
        {"transit_time": "5"},
        'transit_time = "5" has no unit: write transit_time = 5 (a bare number is '
        'in days) or transit_time = "5 days".',
        id="transit time string without unit",
    ),
]


@pytest.mark.parametrize(("fields", "text"), REFUSALS)
def test_refusals(fields, text):
    with pytest.raises(ValidationError, match=re.escape(text)):
        SoilReservoirConfig(**{"ru": 100.0} | fields)


def test_recharge_rate_beside_a_soil_reservoir_is_refused():
    # The soil computes the recharge itself, so a rate written beside it would never reach MODFLOW.
    text = (
        "flow.sinks_sources.recharge.values = 2.0 is ignored when "
        "[flow.sinks_sources.recharge.soil] computes the recharge: remove values, "
        "or remove the soil section to impose this rate."
    )
    with pytest.raises(ValidationError, match=re.escape(text)):
        FlowRechargeConfig(values=2.0, soil=SoilReservoirConfig(ru=100.0))


BOUNDS = [
    pytest.param("ru", {"ge": 0.0, "le": 1000.0}, id="ru"),
    pytest.param("alpha", {"gt": 0.0, "le": 1.0}, id="alpha"),
    pytest.param("kc", {"ge": 0.0, "le": 2.0}, id="kc"),
    pytest.param("impervious_fraction", {"ge": 0.0, "lt": 1.0}, id="impervious_fraction"),
    pytest.param("bypass_fraction", {"ge": 0.0, "lt": 1.0}, id="bypass_fraction"),
    pytest.param("transit_time", {"ge": 0.0, "le": 30.0}, id="transit_time"),
    pytest.param("curve_number", {"ge": 30.0, "le": 98.0}, id="curve_number"),
    pytest.param("runoff_time", {"ge": 0.0, "le": 10.0}, id="runoff_time"),
    pytest.param("runoff_lag", {"ge": 0.0, "le": 5.0}, id="runoff_lag"),
]


@pytest.mark.parametrize(("name", "bounds"), BOUNDS)
def test_range_is_declared_on_the_field(name, bounds):
    declared = {}
    for item in SoilReservoirConfig.model_fields[name].metadata:
        for attr in ("ge", "gt", "le", "lt"):
            if getattr(item, attr, None) is not None:
                declared[attr] = getattr(item, attr)

    assert declared == bounds


def test_ru_reads_a_bare_number_and_a_string_in_millimetres():
    assert SoilReservoirConfig(ru=120).ru == pytest.approx(120.0)
    assert SoilReservoirConfig(ru="120 mm").ru == pytest.approx(120.0)
    assert SoilReservoirConfig(ru="12 cm").ru == pytest.approx(120.0)


def test_transit_time_reads_a_string_in_days():
    assert SoilReservoirConfig(ru=100.0, transit_time="5 days").transit_time == pytest.approx(5.0)


def test_defaults_describe_a_passive_soil():
    config = SoilReservoirConfig(ru=100.0)

    assert config.alpha == pytest.approx(0.45)
    assert config.kc == pytest.approx(1.0)
    assert config.impervious_fraction == pytest.approx(0.0)
    assert config.bypass_fraction == pytest.approx(0.0)
    assert config.transit_time == pytest.approx(0.0)
    assert config.spinup == "first_year"


def one_year_window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2020-01-01"),
        end=pd.Timestamp("2020-12-31"),
        step_value=1,
        step_unit="day",
        coverage_policy="error",
    )


def flow_with_soil(*, flow_regime: str, first_period_steady: bool) -> FlowConfig:
    recharge = FlowRechargeConfig(soil=SoilReservoirConfig(ru=100.0))
    flow = FlowConfig.homogeneous(K=1e-4, flow_regime=flow_regime)
    return flow.model_copy(
        update={
            "sinks_sources": FlowSinksSourcesConfig(recharge=recharge),
            "first_period_steady": first_period_steady,
        }
    )


def test_no_soil_needs_no_refusal():
    flow = FlowConfig.homogeneous(K=1e-4, flow_regime="transient")

    assert steady_start_refusal(flow, one_year_window()) is None


def test_steady_regime_needs_no_refusal():
    flow = flow_with_soil(flow_regime="steady", first_period_steady=True)

    assert steady_start_refusal(flow, one_year_window()) is None
