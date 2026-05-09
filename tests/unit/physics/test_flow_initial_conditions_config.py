import pytest

from hydromodpy.physics.flow.flow_config import FlowConfig
from hydromodpy.physics.flow.initial_conditions_config import (
    normalize_flow_initial_conditions,
)


def test_normalize_flow_initial_conditions_sets_default_h_id() -> None:
    initial_conditions = normalize_flow_initial_conditions(
        {
            "type": "custom",
            "value": 1.0,
            "unit": "m",
        }
    )
    assert initial_conditions is not None
    assert initial_conditions.h.id == "h"


def test_normalize_flow_initial_conditions_rejects_non_empty_payload_without_type() -> None:
    with pytest.raises(ValueError, match="flow.ic.type is required"):
        normalize_flow_initial_conditions({"value": "10 m"})


def test_normalize_flow_initial_conditions_accepts_inline_unit() -> None:
    initial_conditions = normalize_flow_initial_conditions(
        {
            "type": "custom",
            "value": "125 cm",
        }
    )
    assert initial_conditions is not None
    assert initial_conditions.h.value.to("m").magnitude == pytest.approx(1.25)
    assert initial_conditions.h.units == "m"


def test_normalize_flow_initial_conditions_accepts_top_offset() -> None:
    initial_conditions = normalize_flow_initial_conditions(
        {
            "type": "top_offset",
            "value": "10 m",
        }
    )
    assert initial_conditions is not None
    assert initial_conditions.h.type == "top_offset"
    assert initial_conditions.h.value.to("m").magnitude == pytest.approx(10.0)


def test_normalize_flow_initial_conditions_accepts_steady_state_strategy() -> None:
    initial_conditions = normalize_flow_initial_conditions(
        {
            "type": "steady_state",
            "source": "mean_recharge",
            "recharge_statistic": "time_mean",
            "boundary_condition_policy": "first_period",
        }
    )
    assert initial_conditions is not None
    assert initial_conditions.h.type == "steady_state"
    assert initial_conditions.h.source == "mean_recharge"
    assert initial_conditions.h.recharge_statistic == "time_mean"
    assert initial_conditions.h.boundary_condition_policy == "first_period"


def test_normalize_flow_initial_conditions_defaults_steady_state_strategy() -> None:
    initial_conditions = normalize_flow_initial_conditions({"type": "steady_state"})
    assert initial_conditions is not None
    assert initial_conditions.h.source == "mean_recharge"
    assert initial_conditions.h.recharge_statistic == "time_mean"
    assert initial_conditions.h.boundary_condition_policy == "first_period"


def test_flow_config_accepts_steady_state_initial_condition_for_transient() -> None:
    flow_config = FlowConfig(flow_regime="transient", ic={"type": "steady_state"})

    assert flow_config.ic.h.type == "steady_state"


def test_flow_config_rejects_steady_state_initial_condition_for_steady() -> None:
    with pytest.raises(ValueError, match="flow.ic.type='steady_state'"):
        FlowConfig(flow_regime="steady", ic={"type": "steady_state"})


def test_normalize_flow_initial_conditions_rejects_steady_state_value() -> None:
    with pytest.raises(ValueError, match="value is not supported"):
        normalize_flow_initial_conditions({"type": "steady_state", "value": "1 m"})


@pytest.mark.parametrize("ic_type", ["top", "bottom"])
def test_normalize_flow_initial_conditions_rejects_geometry_value(
    ic_type: str,
) -> None:
    with pytest.raises(ValueError, match="value is only supported"):
        normalize_flow_initial_conditions({"type": ic_type, "value": "1 m"})


@pytest.mark.parametrize("ic_type", ["top", "bottom"])
def test_normalize_flow_initial_conditions_rejects_geometry_unit(
    ic_type: str,
) -> None:
    with pytest.raises(ValueError, match="unit/units is only supported"):
        normalize_flow_initial_conditions({"type": ic_type, "unit": "m"})


def test_normalize_flow_initial_conditions_rejects_steady_state_unit() -> None:
    with pytest.raises(ValueError, match="unit/units is not supported"):
        normalize_flow_initial_conditions({"type": "steady_state", "unit": "m"})


def test_normalize_flow_initial_conditions_rejects_conflicting_units() -> None:
    with pytest.raises(ValueError, match="conflicting units"):
        normalize_flow_initial_conditions(
            {
                "type": "custom",
                "value": "1.25 m",
                "unit": "cm",
            }
        )


def test_normalize_flow_initial_conditions_rejects_unknown_units() -> None:
    with pytest.raises(ValueError, match="Unsupported length unit"):
        normalize_flow_initial_conditions(
            {
                "type": "custom",
                "value": "1.25 qblorp",
            }
        )


def test_normalize_flow_initial_conditions_rejects_non_length_units() -> None:
    with pytest.raises(ValueError, match="Unsupported length unit"):
        normalize_flow_initial_conditions(
            {
                "type": "custom",
                "value": "1.25 kg",
            }
        )
