from __future__ import annotations

import pytest

from hydromodpy.model.flow_config import FlowConfig
from hydromodpy.model.initial.config import (
    FlowICBottom,
    FlowICCustom,
    FlowICSpinupCyclic,
    FlowICSteadyState,
    FlowICTop,
    FlowICTopOffset,
    known_ic_types,
    normalize_flow_initial_conditions,
)
from hydromodpy.model.initial.heads import HEAD_INITIAL_CONDITION_TYPES

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
    from hydromodpy.model.initial.config import normalize_flow_initial_conditions

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
