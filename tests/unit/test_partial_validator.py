"""Tests for :mod:`hydromodpy.schema.partial_validator` (P11 frontend hooks)."""

from __future__ import annotations

import time

import pytest


def test_validate_field_valid_enum() -> None:
    from hydromodpy.schema import validate_field

    result = validate_field("flow.flow_regime", "steady")
    assert result.valid is True
    assert result.error is None
    assert result.path == "flow.flow_regime"


def test_validate_field_invalid_enum() -> None:
    from hydromodpy.schema import validate_field

    result = validate_field("flow.flow_regime", "wrong_value")
    assert result.valid is False
    assert result.error is not None
    assert "steady" in result.error or "transient" in result.error


def test_validate_field_unknown_path() -> None:
    from hydromodpy.schema import validate_field

    result = validate_field("flow.does_not_exist", 42)
    assert result.valid is False
    assert result.error is not None


def test_validate_field_empty_path() -> None:
    from hydromodpy.schema import validate_field

    with pytest.raises(ValueError):
        validate_field("", 42)


def test_validate_field_latency_under_100ms() -> None:
    """The per-call cost must stay well below 100 ms for a warm adapter."""
    from hydromodpy.schema import validate_field

    # Warm the adapter cache.
    validate_field("flow.flow_regime", "steady")

    start = time.perf_counter()
    for _ in range(50):
        validate_field("flow.flow_regime", "steady")
    elapsed_ms = (time.perf_counter() - start) * 1000.0 / 50
    assert elapsed_ms < 100, f"mean per-call latency {elapsed_ms:.2f}ms exceeds 100ms"


def test_validate_field_returns_timing() -> None:
    from hydromodpy.schema import validate_field

    result = validate_field("flow.flow_regime", "steady")
    assert result.timing_ms >= 0.0


def test_validation_result_as_dict() -> None:
    from hydromodpy.schema import validate_field

    result = validate_field("flow.flow_regime", "steady")
    payload = result.as_dict()
    assert set(payload.keys()) >= {
        "valid",
        "path",
        "error",
        "warnings",
        "dependent_fields_affected",
        "timing_ms",
    }


def test_validate_field_context_accepted_but_ignored() -> None:
    """The ``context`` argument is currently optional; passing it must not crash."""
    from hydromodpy.schema import validate_field

    ctx = {"flow": {"flow_regime": "transient"}}
    result = validate_field("flow.flow_regime", "steady", context=ctx)
    assert result.valid is True


def test_validate_field_nested_path() -> None:
    """Dotted paths into nested models resolve correctly."""
    # FlowPhysicalProperties is not a direct child of HydroModPyConfig
    # (it is nested under flow_physical_properties via another module),
    # so a path like 'flow.flow_regime' stays the stable smoke test.
    # This case walks a nested BaseModel one level deep.
    from hydromodpy.core.config.hydromodpy_config import HydroModPyConfig
    from hydromodpy.schema import validate_field

    # Pick any nested BaseModel child to confirm traversal works.
    for field_name, info in HydroModPyConfig.model_fields.items():
        ann = info.annotation
        if hasattr(ann, "model_fields"):
            inner = ann
            for leaf_name in inner.model_fields:
                path = f"{field_name}.{leaf_name}"
                # Any validation call should not raise; just confirms we
                # can traverse without crashing.
                validate_field(path, None)
                return
    pytest.skip("no nested BaseModel under HydroModPyConfig")
