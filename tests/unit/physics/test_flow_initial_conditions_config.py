import pytest

from hydromodpy.physics.flow.initial_conditions_config import (
    normalize_flow_initial_conditions,
)


def test_normalize_flow_initial_conditions_sets_default_h_id() -> None:
    initial_conditions = normalize_flow_initial_conditions(
        {
            "type": "top",
            "value": 1.0,
            "unit": "m",
        }
    )
    assert initial_conditions is not None
    assert initial_conditions.h.id == "h"


def test_normalize_flow_initial_conditions_accepts_inline_unit() -> None:
    initial_conditions = normalize_flow_initial_conditions(
        {
            "type": "custom",
            "value": "125 cm",
        }
    )
    assert initial_conditions is not None
    assert initial_conditions.h.value == pytest.approx(1.25)
    assert initial_conditions.h.units == "m"


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
