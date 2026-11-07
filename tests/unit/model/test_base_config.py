from __future__ import annotations

import pytest

from hydromodpy.model.payloads import (
    BoundaryCondition,
    InitialCondition,
    SinkSource,
    normalize_boundary_condition_payload,
    normalize_initial_condition_payload,
    normalize_sink_source_payload,
)


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


def test_normalize_sink_source_payload_passes_through_instances() -> None:
    source = SinkSource(id="well", value=1.5, units="m3/s")

    result = normalize_sink_source_payload(source)

    assert result is source


def test_normalize_sink_source_payload_applies_defaults_and_unit_alias() -> None:
    result = normalize_sink_source_payload(
        {"value": 2.0, "unit": "m3/s"},
        default_id="well",
    )

    assert result.id == "well"
    assert result.value == pytest.approx(2.0)
    assert result.units == "m3/s"


def test_normalize_sink_source_payload_reports_location_for_non_mappings() -> None:
    with pytest.raises(TypeError, match="flow.sinks_sources must be a mapping payload"):
        normalize_sink_source_payload(
            3.0,
            location_prefix="flow.sinks_sources",
        )


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
