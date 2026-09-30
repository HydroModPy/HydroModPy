"""A soil run must not open a transient model on a one-period steady state.

``[flow.sinks_sources.recharge.soil]`` sends each day's recharge to MODFLOW;
solving the first stress period as a steady state under that period's mean
recharge alone would start the run from a drained aquifer.
"""

from __future__ import annotations

import pandas as pd

from hydromodpy.core.time.window import ResolvedSimulationTimeWindow
from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.sinks_sources.container import FlowSinksSourcesConfig
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.physics.hydrology.soil_reservoir.config import (
    SoilReservoirConfig,
    steady_start_refusal,
)


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
        'type = "steady_state", which starts the run from the steady state under '
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
