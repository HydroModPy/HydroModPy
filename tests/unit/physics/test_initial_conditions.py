from __future__ import annotations

from types import SimpleNamespace

import pytest

from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.initial_conditions import (
    FlowICBottom,
    FlowICCustom,
    FlowICSpinupCyclic,
    FlowICSteadyState,
    FlowICTop,
    FlowICTopOffset,
    FlowInitialConditions,
)
from hydromodpy.physics.flow.initial_conditions_config import (
    known_ic_types,
    normalize_flow_initial_conditions,
)
from hydromodpy.physics.flow.sinks_sources.recharge import FlowRechargeConfig
from hydromodpy.solver.initial_conditions import HEAD_INITIAL_CONDITION_TYPES
from hydromodpy.solver.steady_initial_conditions import (
    apply_steady_state_initial_condition_strategy,
    steady_state_initial_condition_strategy,
)

# Every list of accepted initial-condition types has to be the same list.
#
# The repository carried three: the config loader's key set, the config loader's type
# set, and the solver's tuple. Adding ``spinup_cyclic`` to the union passed validation
# and then failed inside ``run_solver`` with a message enumerating the variants the
# solver happened to know. That contradiction is invisible to a reader, and it cost a
# real model run to find, so it is gated here instead.


VARIANTS = (
    FlowICTop,
    FlowICTopOffset,
    FlowICBottom,
    FlowICCustom,
    FlowICSteadyState,
    FlowICSpinupCyclic,
)


def test_the_config_loader_accepts_exactly_the_union_s_discriminators() -> None:
    assert known_ic_types() == {str(variant.model_fields["kind"].default) for variant in VARIANTS}


def test_the_solver_accepts_exactly_the_same_ones() -> None:
    assert set(HEAD_INITIAL_CONDITION_TYPES) == known_ic_types()


def test_every_variant_is_reachable_from_a_toml_payload() -> None:
    # The one check that would have caught it end to end: each discriminator has to
    # survive the flat [flow.ic] form the loader accepts.
    from hydromodpy.physics.flow.initial_conditions_config import (
        normalize_flow_initial_conditions,
    )

    required = {"custom": {"value": 42.0}, "top_offset": {"value": 0.5}}
    for name in sorted(known_ic_types()):
        payload = {"kind": name, **required.get(name, {})}
        resolved = normalize_flow_initial_conditions(payload, location_prefix="flow.ic")
        assert resolved is not None
        assert resolved.h.kind == name


def test_normalize_flow_initial_conditions_sets_default_h_id() -> None:
    initial_conditions = normalize_flow_initial_conditions(
        {
            "kind": "custom",
            "value": 1.0,
            "unit": "m",
        }
    )
    assert initial_conditions is not None
    assert initial_conditions.h.id == "h"


def test_normalize_flow_initial_conditions_rejects_non_empty_payload_without_type() -> None:
    with pytest.raises(ValueError, match="flow.ic.kind is required"):
        normalize_flow_initial_conditions({"value": "10 m"})


def test_normalize_flow_initial_conditions_accepts_inline_unit() -> None:
    initial_conditions = normalize_flow_initial_conditions(
        {
            "kind": "custom",
            "value": "125 cm",
        }
    )
    assert initial_conditions is not None
    assert initial_conditions.h.value.to("m").magnitude == pytest.approx(1.25)
    assert initial_conditions.h.units == "m"


def test_normalize_flow_initial_conditions_accepts_top_offset() -> None:
    initial_conditions = normalize_flow_initial_conditions(
        {
            "kind": "top_offset",
            "value": "10 m",
        }
    )
    assert initial_conditions is not None
    assert initial_conditions.h.kind == "top_offset"
    assert initial_conditions.h.value.to("m").magnitude == pytest.approx(10.0)


def test_normalize_flow_initial_conditions_accepts_steady_state_strategy() -> None:
    initial_conditions = normalize_flow_initial_conditions(
        {
            "kind": "steady_state",
            "source": "mean_recharge",
            "recharge_statistic": "time_mean",
            "boundary_condition_policy": "first_period",
        }
    )
    assert initial_conditions is not None
    assert initial_conditions.h.kind == "steady_state"
    assert initial_conditions.h.source == "mean_recharge"
    assert initial_conditions.h.recharge_statistic == "time_mean"
    assert initial_conditions.h.boundary_condition_policy == "first_period"


def test_normalize_flow_initial_conditions_defaults_steady_state_strategy() -> None:
    initial_conditions = normalize_flow_initial_conditions({"kind": "steady_state"})
    assert initial_conditions is not None
    assert initial_conditions.h.source == "mean_recharge"
    assert initial_conditions.h.recharge_statistic == "time_mean"
    assert initial_conditions.h.boundary_condition_policy == "first_period"


def test_flow_config_accepts_steady_state_initial_condition_for_transient() -> None:
    flow_config = FlowConfig(flow_regime="transient", ic={"kind": "steady_state"})

    assert flow_config.ic.h.kind == "steady_state"


def test_flow_config_rejects_steady_state_initial_condition_for_steady() -> None:
    with pytest.raises(ValueError, match="flow.ic.kind='steady_state'"):
        FlowConfig(flow_regime="steady", ic={"kind": "steady_state"})


def test_normalize_flow_initial_conditions_rejects_steady_state_value() -> None:
    with pytest.raises(ValueError, match="value is not supported"):
        normalize_flow_initial_conditions({"kind": "steady_state", "value": "1 m"})


@pytest.mark.parametrize("ic_type", ["top", "bottom"])
def test_normalize_flow_initial_conditions_rejects_geometry_value(
    ic_type: str,
) -> None:
    with pytest.raises(ValueError, match="value is only supported"):
        normalize_flow_initial_conditions({"kind": ic_type, "value": "1 m"})


@pytest.mark.parametrize("ic_type", ["top", "bottom"])
def test_normalize_flow_initial_conditions_rejects_geometry_unit(
    ic_type: str,
) -> None:
    with pytest.raises(ValueError, match="unit/units is only supported"):
        normalize_flow_initial_conditions({"kind": ic_type, "unit": "m"})


def test_normalize_flow_initial_conditions_rejects_steady_state_unit() -> None:
    with pytest.raises(ValueError, match="unit/units is not supported"):
        normalize_flow_initial_conditions({"kind": "steady_state", "unit": "m"})


def test_normalize_flow_initial_conditions_rejects_conflicting_units() -> None:
    with pytest.raises(ValueError, match="conflicting units"):
        normalize_flow_initial_conditions(
            {
                "kind": "custom",
                "value": "1.25 m",
                "unit": "cm",
            }
        )


def test_normalize_flow_initial_conditions_rejects_unknown_units() -> None:
    with pytest.raises(ValueError, match="Unsupported length unit"):
        normalize_flow_initial_conditions(
            {
                "kind": "custom",
                "value": "1.25 qblorp",
            }
        )


def test_normalize_flow_initial_conditions_rejects_non_length_units() -> None:
    with pytest.raises(ValueError, match="Unsupported length unit"):
        normalize_flow_initial_conditions(
            {
                "kind": "custom",
                "value": "1.25 kg",
            }
        )


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


def _flow(ic_payload: dict[str, object], **sinks_sources: object) -> SimpleNamespace:
    """Return the smallest object the strategy helpers read."""
    return SimpleNamespace(
        initial_conditions=FlowInitialConditions(
            h=FlowICSteadyState.model_validate({"kind": "steady_state", **ic_payload})
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
        FlowICSteadyState.model_validate({"kind": "steady_state", "source": "prescribed"})


def test_a_rate_without_a_prescribed_source_is_refused() -> None:
    """A rate that nothing reads would be a silent no-op."""
    with pytest.raises(ValueError, match="prescribed"):
        FlowICSteadyState.model_validate(
            {"kind": "steady_state", "source": "mean_recharge", "rate": "500 mm/yr"}
        )


def test_a_chronicle_statistic_alongside_a_prescribed_rate_is_refused() -> None:
    with pytest.raises(ValueError, match="recharge_statistic"):
        FlowICSteadyState.model_validate(
            {
                "kind": "steady_state",
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
