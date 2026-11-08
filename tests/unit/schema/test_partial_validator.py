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


def test_validate_field_rejects_noncanonical_flow_regime() -> None:
    from hydromodpy.schema import validate_field

    result = validate_field("flow.flow_regime", "permanent")
    assert result.valid is False
    assert result.error is not None
    assert "steady" in result.error or "transient" in result.error


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
    assert "does_not_exist" in result.error or "unknown" in result.error.lower()


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
    from hydromodpy.config import HydroModPyConfig
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
    pytest.fail("HydroModPyConfig exposes no nested BaseModel field to validate")


FIELD_CASES = (
    ("solver.backend", "modflow_nwt", True, None),
    ("solver.backend", " Boussinesq ", True, None),
    (
        "solver.backend",
        "nope",
        False,
        "solver.backend names 'nope', and this installation serves boussinesq, modflow6, "
        "modflow_nwt",
    ),
    ("mesh.engine", " triangle ", True, None),
    (
        "mesh.engine",
        "nope",
        False,
        "mesh.engine names 'nope', and this installation serves catchment, regular, triangle, voronoi",
    ),
    ("geographic.terrain_engine", None, True, None),
    (
        "geographic.terrain_engine",
        "nope",
        False,
        "geographic.terrain_engine names 'nope', and this installation serves numpy_d8",
    ),
    ("calibration.evaluator", None, True, None),
    (
        "calibration.evaluator",
        "nope",
        False,
        "calibration.evaluator names 'nope', and this installation serves analytic_bowl",
    ),
    ("calibration.forward_model", "linear_reservoir", True, None),
    (
        "calibration.forward_model",
        "nope",
        False,
        "calibration.forward_model names 'nope', and this installation serves linear_reservoir",
    ),
    ("solver.modflow6.runtime.mf6_ims_complexity", "SIMPLE", True, None),
    ("solver.modflow6.runtime.mf6_ims_complexity", "x", False, "Input should be"),
    ("solver.boussinesq.max_iterations", 40, True, None),
    ("solver.drain_bed_thickness_m", -1.0, False, "greater than 0"),
)


@pytest.mark.parametrize(("path", "value", "valid", "error"), FIELD_CASES)
def test_a_field_is_checked_as_the_file_is_read(
    path: str, value: object, valid: bool, error: str | None
) -> None:
    """The checks of the annotation run here too: the registry, a bound, a named table."""
    from hydromodpy.schema import validate_field

    result = validate_field(path, value)

    assert result.valid is valid
    if error is not None:
        assert error in (result.error or "")
