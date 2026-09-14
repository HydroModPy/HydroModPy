"""A steady initial state must be reachable at a rate the user chooses.

The steady-state initial condition solved under the mean of the whole chronicle
and nothing else: its ``source`` was a closed pair whose two values both forced
the same time mean. A study that wants its transient to start from equilibrium
under a stated recharge, a design rate, a pre-development baseline or a
scenario, had no way to say so through this mechanism.

The rate carries its unit, and it reaches the solve whatever shape the recharge
payload has: ``first_clim`` alone is read only for a sequence payload, so a
prescribed rate that only wrote ``first_clim`` would be a silent no-op on a
scalar or per-cell recharge.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.physics.flow.initial_conditions import (
    FlowICSteadyState,
    FlowInitialConditions,
)
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.steady_initial_conditions import (
    apply_steady_state_initial_condition_strategy,
    steady_state_initial_condition_strategy,
)

_MM_PER_YEAR_IN_M_PER_S = 1e-3 / (365.25 * 86400.0)


def _flow(ic_payload: dict[str, object], **sinks_sources: object) -> SimpleNamespace:
    """Return the smallest object the strategy helpers read."""
    return SimpleNamespace(
        initial_conditions=FlowInitialConditions(
            h=FlowICSteadyState.model_validate({"type": "steady_state", **ic_payload})
        ),
        sinks_sources=dict(sinks_sources),
    )


def test_a_prescribed_rate_is_accepted_with_its_unit() -> None:
    strategy = steady_state_initial_condition_strategy(
        _flow({"source": "prescribed", "rate": "500 mm/yr"})
    )

    assert strategy is not None
    assert strategy.source == "prescribed"
    assert strategy.rate_m_s == pytest.approx(500 * _MM_PER_YEAR_IN_M_PER_S, rel=1e-9)


def test_the_mean_of_the_record_stays_the_default() -> None:
    strategy = steady_state_initial_condition_strategy(_flow({}))

    assert strategy is not None
    assert strategy.source == "mean_recharge"
    assert strategy.recharge_statistic == "time_mean"
    assert strategy.rate_m_s is None


def test_a_prescribed_source_without_a_rate_is_refused() -> None:
    with pytest.raises(ValueError, match="rate"):
        FlowICSteadyState.model_validate({"type": "steady_state", "source": "prescribed"})


def test_a_rate_without_a_prescribed_source_is_refused() -> None:
    """A rate that nothing reads would be a silent no-op."""
    with pytest.raises(ValueError, match="prescribed"):
        FlowICSteadyState.model_validate(
            {"type": "steady_state", "source": "mean_recharge", "rate": "500 mm/yr"}
        )


def test_a_chronicle_statistic_alongside_a_prescribed_rate_is_refused() -> None:
    with pytest.raises(ValueError, match="recharge_statistic"):
        FlowICSteadyState.model_validate(
            {
                "type": "steady_state",
                "source": "prescribed",
                "rate": "500 mm/yr",
                "recharge_statistic": "time_mean",
            }
        )


def test_a_bare_number_is_read_in_metres_per_second() -> None:
    """The unit is part of the value, and a bare number keeps the SI meaning."""
    strategy = steady_state_initial_condition_strategy(
        _flow({"source": "prescribed", "rate": 1.5844e-8})
    )

    assert strategy is not None
    assert strategy.rate_m_s == pytest.approx(1.5844e-8)


def test_the_prescribed_rate_replaces_a_scalar_recharge_payload() -> None:
    """`first_clim` is ignored for a scalar payload, so the values must move too."""
    flow = _flow(
        {"source": "prescribed", "rate": "500 mm/yr"},
        recharge=FlowRechargeConfig(values=1e-9, units="m/s"),
    )

    apply_steady_state_initial_condition_strategy(flow)

    recharge = flow.sinks_sources["recharge"]
    assert recharge.values == pytest.approx(500 * _MM_PER_YEAR_IN_M_PER_S, rel=1e-9)
    assert recharge.first_clim == pytest.approx(500 * _MM_PER_YEAR_IN_M_PER_S, rel=1e-9)


def test_the_prescribed_rate_is_written_in_the_payload_unit() -> None:
    flow = _flow(
        {"source": "prescribed", "rate": "500 mm/yr"},
        recharge=FlowRechargeConfig(values=[1.0, 2.0], units="mm/day"),
    )

    apply_steady_state_initial_condition_strategy(flow)

    recharge = flow.sinks_sources["recharge"]
    assert recharge.values == pytest.approx(500.0 / 365.25, rel=1e-9)


def test_a_prescribed_rate_drops_a_heterogeneous_recharge_field() -> None:
    """One stated rate means one uniform rate; a per-cell field would win otherwise."""
    flow = _flow(
        {"source": "prescribed", "rate": "500 mm/yr"},
        recharge=FlowRechargeConfig(values=0.0, units="m/s", heterogeneous_source=object()),
    )

    apply_steady_state_initial_condition_strategy(flow)

    assert flow.sinks_sources["recharge"].heterogeneous_source is None


def test_the_mean_strategy_still_only_touches_the_first_period() -> None:
    flow = _flow({}, recharge=FlowRechargeConfig(values=[1.0, 2.0], units="mm/day"))

    apply_steady_state_initial_condition_strategy(flow)

    recharge = flow.sinks_sources["recharge"]
    assert recharge.first_clim == "mean"
    assert list(recharge.values) == [1.0, 2.0]
