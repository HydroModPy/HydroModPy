from __future__ import annotations

import pytest

from hydromodpy.physics.base import BoundaryCondition, normalize_boundary_condition_payload


def test_normalize_boundary_condition_payload_passes_through_instances() -> None:
    condition = BoundaryCondition(id="sea", value=1.5, units="m")

    result = normalize_boundary_condition_payload(condition)

    assert result is condition


def test_normalize_boundary_condition_payload_applies_defaults_and_unit_alias() -> None:
    result = normalize_boundary_condition_payload(
        {"value": 2.0, "unit": "m"},
        default_id="west_bc",
    )

    assert result.id == "west_bc"
    assert result.value == pytest.approx(2.0)
    assert result.units == "m"


def test_normalize_boundary_condition_payload_reports_location_for_non_mappings() -> None:
    with pytest.raises(TypeError, match="flow.bc.ocean must be a mapping payload"):
        normalize_boundary_condition_payload(
            3.0,
            location_prefix="flow.bc.ocean",
        )
