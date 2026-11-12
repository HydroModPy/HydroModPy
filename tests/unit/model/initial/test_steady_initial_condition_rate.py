"""The steady initial state is solved at the rate the user chooses, with its unit."""

from __future__ import annotations

import pytest

from hydromodpy.model.initial.state import SteadyStart
from hydromodpy.model.initial_config import FlowICSteadyState, steady_state_strategy_of
from hydromodpy.model.model import ModelTime, steady_variant
from hydromodpy.model.sinks_sources.recharge import FlowRechargeConfig
from tests._helpers.model_factory import make_model, time_grid

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


def test_a_bare_number_is_read_in_metres_per_second() -> None:
    # A bare number keeps the SI meaning, m/s.
    strategy = steady_state_strategy_of(_ic(source="prescribed", rate=1.5844e-8))

    assert strategy.rate_m_s == pytest.approx(1.5844e-8)


def test_the_prescribed_rate_replaces_a_scalar_recharge_payload() -> None:
    # first_clim alone is ignored for a scalar payload, so the values must move too.
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


REFUSALS = [
    pytest.param({"source": "prescribed"}, "rate", id="prescribed without a rate"),
    pytest.param(
        {"source": "mean_recharge", "rate": "500 mm/yr"}, "prescribed", id="rate without prescribed"
    ),
    pytest.param(
        {"source": "prescribed", "rate": "500 mm/yr", "recharge_statistic": "time_mean"},
        "recharge_statistic",
        id="statistic beside a prescribed rate",
    ),
]


@pytest.mark.parametrize(("payload", "match"), REFUSALS)
def test_refusals(payload, match):
    with pytest.raises(ValueError, match=match):
        _ic(**payload)
