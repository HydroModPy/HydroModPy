"""The steady initial state is solved at the rate the user chooses, with its unit."""

from __future__ import annotations

import pytest

from hydromodpy.model.initial.state import SteadyStart
from hydromodpy.model.initial_config import FlowICSteadyState, steady_state_strategy_of
from hydromodpy.model.model import ModelTime, steady_variant
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from tests._helpers.model_factory import make_model, time_grid

# A steady initial state must be reachable at a rate the user chooses.
#
# The steady-state initial condition solved under the mean of the whole chronicle
# and nothing else: its ``source`` was a closed pair whose two values both forced
# the same time mean. A study that wants its transient to start from equilibrium
# under a stated recharge, a design rate, a pre-development baseline or a
# scenario, had no way to say so through this mechanism.
#
# The rate carries its unit, and it reaches the solve whatever shape the recharge
# payload has: ``first_clim`` alone is read only for a sequence payload, so a
# prescribed rate that only wrote ``first_clim`` would be a silent no-op on a
# scalar or per-cell recharge.


_MM_PER_YEAR_IN_M_PER_S = 1e-3 / (365.25 * 86400.0)


def _ic(**payload: object) -> FlowICSteadyState:
    return FlowICSteadyState.model_validate({"kind": "steady_state", **payload})


def _steady_recharge(recharge: FlowRechargeConfig, **payload: object) -> FlowRechargeConfig:
    """The recharge the auxiliary steady solve reads for this ``[flow.ic]``."""
    model = make_model(
        recharge=recharge,
        initial=SteadyStart(steady_state_strategy_of(_ic(**payload))),
        time=ModelTime(grid=time_grid(10.0, 20.0), regime="transient", first_period_steady=True),
    )
    return steady_variant(model).recharge


def test_a_prescribed_rate_is_accepted_with_its_unit() -> None:
    strategy = steady_state_strategy_of(_ic(source="prescribed", rate="500 mm/yr"))

    assert strategy.source == "prescribed"
    assert strategy.rate_m_s == pytest.approx(500 * _MM_PER_YEAR_IN_M_PER_S, rel=1e-9)


def test_a_prescribed_source_without_a_rate_is_refused() -> None:
    with pytest.raises(ValueError, match="rate"):
        _ic(source="prescribed")


def test_a_rate_without_a_prescribed_source_is_refused() -> None:
    """A rate that nothing reads would be a silent no-op."""
    with pytest.raises(ValueError, match="prescribed"):
        _ic(source="mean_recharge", rate="500 mm/yr")


def test_a_chronicle_statistic_alongside_a_prescribed_rate_is_refused() -> None:
    with pytest.raises(ValueError, match="recharge_statistic"):
        _ic(source="prescribed", rate="500 mm/yr", recharge_statistic="time_mean")


def test_a_bare_number_is_read_in_metres_per_second() -> None:
    """The unit is part of the value, and a bare number keeps the SI meaning."""
    strategy = steady_state_strategy_of(_ic(source="prescribed", rate=1.5844e-8))

    assert strategy.rate_m_s == pytest.approx(1.5844e-8)


def test_the_prescribed_rate_replaces_a_scalar_recharge_payload() -> None:
    """`first_clim` is ignored for a scalar payload, so the values must move too."""
    recharge = _steady_recharge(
        FlowRechargeConfig(values=1e-9, units="m/s"), source="prescribed", rate="500 mm/yr"
    )

    assert recharge.values == pytest.approx(500 * _MM_PER_YEAR_IN_M_PER_S, rel=1e-9)
    assert recharge.first_clim == pytest.approx(500 * _MM_PER_YEAR_IN_M_PER_S, rel=1e-9)


def test_the_prescribed_rate_is_written_in_the_payload_unit() -> None:
    recharge = _steady_recharge(
        FlowRechargeConfig(values=[1.0, 2.0], units="mm/day"), source="prescribed", rate="500 mm/yr"
    )

    assert recharge.values == pytest.approx(500.0 / 365.25, rel=1e-9)
