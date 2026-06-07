from __future__ import annotations

import pytest

from hydromodpy.physics.base import InitialCondition, normalize_initial_condition_payload


def test_normalize_initial_condition_payload_passes_through_instances() -> None:
    condition = InitialCondition(id="h0", value=1.5, units="m")

    result = normalize_initial_condition_payload(condition)

    assert result is condition


def test_normalize_initial_condition_payload_accepts_numeric_scalars() -> None:
    result = normalize_initial_condition_payload(2.0, default_id="head")

    assert result.id == "head"
    assert result.value == pytest.approx(2.0)
    assert result.units == ""


def test_normalize_initial_condition_payload_applies_unit_alias() -> None:
    result = normalize_initial_condition_payload(
        {"value": 2.0, "unit": "m"},
        default_id="head",
    )

    assert result.id == "head"
    assert result.value == pytest.approx(2.0)
    assert result.units == "m"


def test_normalize_initial_condition_payload_rejects_bool_values() -> None:
    with pytest.raises(TypeError, match="flow.ic must be a mapping or numeric value"):
        normalize_initial_condition_payload(True, location_prefix="flow.ic")


def test_normalize_initial_condition_payload_reports_location_for_non_mappings() -> None:
    with pytest.raises(TypeError, match="flow.ic must be a mapping payload"):
        normalize_initial_condition_payload(
            "bad",
            location_prefix="flow.ic",
        )
