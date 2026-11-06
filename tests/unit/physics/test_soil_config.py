from __future__ import annotations

import re

import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.physics.hydrology.soil_reservoir.config import (
    SoilReservoirConfig,
    spinup_refusal,
    steady_start_refusal,
)

# A recharge rate written beside a soil reservoir would be silently ignored.
#
# ``[flow.sinks_sources.recharge.soil]`` computes the recharge itself, so a
# ``values`` written in the same section names a rate MODFLOW never sees.


def test_a_recharge_rate_beside_a_soil_reservoir_is_refused() -> None:
    text = (
        "flow.sinks_sources.recharge.values = 2.0 is ignored when "
        "[flow.sinks_sources.recharge.soil] computes the recharge: remove values, "
        "or remove the soil section to impose this rate."
    )
    with pytest.raises(ValidationError, match=re.escape(text)):
        FlowRechargeConfig(values=2.0, soil=SoilReservoirConfig(ru=100.0))


def test_a_recharge_rate_built_by_code_without_soil_passes() -> None:
    recharge = FlowRechargeConfig(values=0.0)

    assert recharge.soil is None
    assert recharge.values == 0.0


# Repeating the first year to spin up the soil needs a run of a year at least.
#
# ``spinup = "first_year"`` repeats the first 52 weeks (364 days) of the run; a shorter
# run never sees a full first year to repeat.


def test_a_run_shorter_than_a_year_is_refused() -> None:
    config = SoilReservoirConfig(ru=100.0)

    refusal = spinup_refusal(config, 363)

    assert refusal == (
        'spinup = "first_year" repeats the first 52 weeks (364 days) of the run, and '
        '[simulation.time] covers 363 days: write spinup = "none" under '
        "[flow.sinks_sources.recharge.soil] to start from a full soil, or extend "
        "the run to 52 weeks at least."
    )


def test_a_year_long_run_needs_no_refusal() -> None:
    config = SoilReservoirConfig(ru=100.0)

    assert spinup_refusal(config, 365) is None


def test_no_spinup_needs_no_refusal() -> None:
    config = SoilReservoirConfig(ru=100.0, spinup="none")

    assert spinup_refusal(config, 10) is None


# A soil run must not open a transient model on a one-period steady state.
#
# ``[flow.sinks_sources.recharge.soil]`` sends each day's recharge to MODFLOW;
# solving the first stress period as a steady state under that period's mean
# recharge alone would start the run from a drained aquifer.


def _window() -> ResolvedSimulationTimeWindow:
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2020-01-01"),
        end=pd.Timestamp("2020-12-31"),
        step_value=1,
        step_unit="day",
        coverage_policy="error",
    )


def _flow_with_soil(*, flow_regime: str, first_period_steady: bool) -> FlowConfig:
    soil = SoilReservoirConfig(ru=100.0)
    recharge = FlowRechargeConfig(soil=soil)
    sinks_sources = FlowSinksSourcesConfig(recharge=recharge)
    flow = FlowConfig.homogeneous(K=1e-4, flow_regime=flow_regime)
    return flow.model_copy(
        update={"sinks_sources": sinks_sources, "first_period_steady": first_period_steady}
    )


def test_a_transient_soil_run_on_a_steady_first_period_is_refused() -> None:
    flow = _flow_with_soil(flow_regime="transient", first_period_steady=True)

    refusal = steady_start_refusal(flow, _window())

    assert refusal == (
        "[flow.sinks_sources.recharge.soil] sends each day's recharge to MODFLOW, "
        "and flow.first_period_steady = true solves the first stress period "
        "(1 day) as a steady state under that period's recharge alone, zero after "
        "a dry day: the run would start from a drained aquifer. Write "
        "first_period_steady = false under [flow] and add [flow.ic] "
        'kind = "steady_state", which starts the run from the steady state under '
        "the mean recharge of the whole run."
    )


def test_no_soil_needs_no_refusal() -> None:
    flow = FlowConfig.homogeneous(K=1e-4, flow_regime="transient")

    assert steady_start_refusal(flow, _window()) is None


def test_a_steady_regime_needs_no_refusal() -> None:
    flow = _flow_with_soil(flow_regime="steady", first_period_steady=True)

    assert steady_start_refusal(flow, _window()) is None


def test_first_period_steady_false_needs_no_refusal() -> None:
    flow = _flow_with_soil(flow_regime="transient", first_period_steady=False)

    assert steady_start_refusal(flow, _window()) is None


# The soil section reads a hydrogeologist's request, not a Pydantic internal.
#
# ``ru`` and ``transit_time`` carry their own unit, so a file writes ``"120 mm"``
# or ``"5 days"`` and the section reads the same value as a bare number in the
# canonical unit. ``ru`` has no default: it belongs to the site, so a file that
# omits it is refused rather than started from a silent guess.


def test_ru_reads_a_bare_number_and_a_string_in_millimetres() -> None:
    assert SoilReservoirConfig(ru=120).ru == pytest.approx(120.0)
    assert SoilReservoirConfig(ru="120 mm").ru == pytest.approx(120.0)
    assert SoilReservoirConfig(ru="12 cm").ru == pytest.approx(120.0)


def test_transit_time_reads_a_string_in_days() -> None:
    config = SoilReservoirConfig(ru=100.0, transit_time="5 days")

    assert config.transit_time == pytest.approx(5.0)


def test_the_defaults_describe_a_passive_soil() -> None:
    config = SoilReservoirConfig(ru=100.0)

    assert config.alpha == pytest.approx(0.45)
    assert config.kc == pytest.approx(1.0)
    assert config.impervious_fraction == pytest.approx(0.0)
    assert config.bypass_fraction == pytest.approx(0.0)
    assert config.transit_time == pytest.approx(0.0)
    assert config.spinup == "first_year"


def test_ru_is_required() -> None:
    with pytest.raises(ValidationError):
        SoilReservoirConfig()
