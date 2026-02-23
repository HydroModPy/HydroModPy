"""
Generic case orchestration for calibration2.

This module runs one complete calibration workflow from a validated config and
one `AbstractCalibrationCase` implementation. It keeps orchestration logic in a
single place so case files can focus on scientific/model-specific code.

High-level flow implemented here
--------------------------------
1) Validate global calibration config.
2) Ask the case to validate its own chronicle/config section.
3) Ask the case to build a `CalibrationCaseContext`.
4) Resolve method/metric/bounds settings.
5) Run `CalibrationEngine.calibrate(...)`.
6) Ask the case to optionally build additional output fields.

Design intent
-------------
- `core/` owns generic execution and calibration mechanics.
- `cases/...` own model equations, forcing, chronicle generation, and
  domain-specific diagnostics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from hydromodpy.calibration2.core.case_interface import (
    CalibrationCaseContext,
    validate_case_implementation,
)
from hydromodpy.calibration2.core.engine import CalibrationEngine
from hydromodpy.calibration2.core.engine_config import (
    load_calibration_toml,
    resolve_calibration_settings,
    validate_calibration_config_data,
)
from hydromodpy.calibration2.core.results import CalibrationResults


def _mapping_or_empty(values, *, name):
    if values is None:
        return {}
    if not isinstance(values, Mapping):
        raise TypeError(f"{name} must be a mapping")
    return dict(values)


def run_calibration_case(
    config_data,
    case_implementation,
    *,
    method_override=None,
):
    """
    Run one full calibration using a validated case implementation.

    Parameters
    ----------
    config_data : Mapping[str, Any]
        Raw or validated calibration payload (same structure as TOML content).
    case_implementation : object
        Instance inheriting `AbstractCalibrationCase`.
    method_override : str | None
        Optional method override. When None, uses `[calibration].global_method`.

    Returns
    -------
    dict
        Standardized payload containing engine, result, settings and
        case-specific post-processed values.
    """
    case_name = validate_case_implementation(case_implementation)
    validated_config = validate_calibration_config_data(config_data)

    chronicle_section = _mapping_or_empty(validated_config.get("chronicle"), name="chronicle")
    calibration_section = _mapping_or_empty(validated_config.get("calibration"), name="calibration")
    case_config = case_implementation.validate_case_config(
        chronicle_section,
        calibration_section=calibration_section,
        full_config=validated_config,
    )
    case_config = _mapping_or_empty(case_config, name="case config")

    case_context = case_implementation.build_case(
        case_config,
        calibration_section=calibration_section,
        full_config=validated_config,
    )
    if not isinstance(case_context, CalibrationCaseContext):
        raise TypeError("build_case(...) must return CalibrationCaseContext")

    settings = resolve_calibration_settings(
        validated_config,
        model_parameter_order=case_context.parameter_order,
    )
    selected_method = settings["method"] if method_override is None else str(method_override)

    calibration_engine = CalibrationEngine(
        observed=case_context.observed,
        simulator=case_context.simulator,
        parameter_set=settings["parameter_set"],
        objective_metric=settings["objective_metric"],
    )
    result = calibration_engine.calibrate(
        method=selected_method,
        **settings["method_kwargs"],
    )
    if not isinstance(result, CalibrationResults):
        raise TypeError("CalibrationEngine.calibrate(...) must return CalibrationResults")

    payload = {
        "case_name": case_name,
        "config": validated_config,
        "case_config": case_config,
        "chronicle": case_context.chronicle,
        "build_metadata": dict(case_context.metadata),
        "calibration_obj": calibration_engine,
        "result": result,
        "method": selected_method,
        "objective_metric": settings["objective_metric"],
        "bounds": settings["bounds"],
        "parameter_set": settings["parameter_set"],
        "parameter_names": settings["parameter_names"],
        "method_kwargs": settings["method_kwargs"],
    }

    extra = case_implementation.build_case_outputs(
        config=validated_config,
        case_config=case_config,
        case_context=case_context,
        calibration_engine=calibration_engine,
        result=result,
        settings=settings,
    )
    if extra is not None:
        payload.update(_mapping_or_empty(extra, name="build_case_outputs return"))

    return payload


def run_calibration_case_from_toml(
    config_path,
    case_implementation,
    *,
    method_override=None,
):
    """
    Load TOML and run one full case calibration.
    """
    config = load_calibration_toml(Path(config_path))
    return run_calibration_case(
        config_data=config,
        case_implementation=case_implementation,
        method_override=method_override,
    )


__all__ = (
    "run_calibration_case",
    "run_calibration_case_from_toml",
)
