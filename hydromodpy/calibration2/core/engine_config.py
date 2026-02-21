"""Pydantic schemas for calibration2 generic configuration payloads."""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any, Mapping
import warnings

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from hydromodpy.calibration2.core.parameters import CalibrationParameterSet
from hydromodpy.calibration2.core.objective_function import ObjectiveFunction
from hydromodpy.calibration2.core.methods_config import (
    is_supported_method,
    normalize_format_method_kwargs,
    validate_calibration_method_section_or_raise,
)


class CalibrationSectionSchema(BaseModel):
    """Generic `[calibration]` section used by calibration2 cases."""

    model_config = ConfigDict(extra="forbid")

    objective_metric: str = "kge"
    global_method: str = "simplex"
    model_name: str | None = None

    @field_validator("objective_metric", "global_method")
    @classmethod
    def _validate_non_empty_str(cls, value):
        text = str(value).strip()
        if not text:
            raise ValueError("value cannot be empty")
        return text

    @field_validator("objective_metric")
    @classmethod
    def _validate_objective_metric(cls, value):
        return ObjectiveFunction.resolve_metric_name(value)

    @field_validator("global_method")
    @classmethod
    def _canonicalize_global_method(cls, value):
        method = str(value).strip().lower()
        if not is_supported_method(method):
            raise ValueError(f"Unsupported global_method '{value}'")
        return method

    @field_validator("model_name")
    @classmethod
    def _validate_optional_model_name(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("model_name cannot be empty")
        return text


class CalibrationTomlSchema(BaseModel):
    """Top-level TOML schema for calibration examples."""

    model_config = ConfigDict(extra="forbid")

    chronicle: dict[str, Any]
    calibration: CalibrationSectionSchema
    bounds: dict[str, tuple[float, float] | list[float]]
    calibration_method: dict[str, dict[str, Any]] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)

    @field_validator("chronicle", "output")
    @classmethod
    def _validate_mapping_sections(cls, value):
        if not isinstance(value, Mapping):
            raise ValueError("section must be a mapping")
        return dict(value)

    @field_validator("bounds")
    @classmethod
    def _validate_bounds(cls, value):
        if not isinstance(value, Mapping) or not value:
            raise ValueError("[bounds] must be a non-empty mapping")

        parsed: dict[str, tuple[float, float]] = {}
        for raw_name, pair in value.items():
            name = str(raw_name)
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError(f"Bounds for '{name}' must be a 2-value list/tuple")
            low = float(pair[0])
            high = float(pair[1])
            if low >= high:
                raise ValueError(f"Invalid bounds for '{name}': lower must be < upper")
            parsed[name] = (low, high)
        return parsed

    @field_validator("calibration_method")
    @classmethod
    def _validate_calibration_method_section(cls, value):
        return validate_calibration_method_section_or_raise(value)


def validate_calibration_config_data(
    config_data: Mapping[str, Any],
    *,
    required_sections: tuple[str, ...] = (),
) -> dict[str, Any]:
    """
    Validate raw calibration config data and return a normalized dict payload.
    """
    if not isinstance(config_data, Mapping):
        raise ValueError("configuration must be a mapping")

    for section in required_sections:
        if section not in config_data:
            raise KeyError(f"Missing required section '{section}'")

    try:
        validated = CalibrationTomlSchema.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return validated.model_dump(mode="python")


def load_calibration_toml(
    config_path,
    *,
    required_sections=("chronicle", "calibration", "bounds"),
):
    """
    Load calibration TOML and validate/normalize top-level sections.
    """
    path = Path(config_path)
    with path.open("rb") as stream:
        config = tomllib.load(stream)

    for section in required_sections:
        if section not in config:
            raise KeyError(f"Missing [{section}] section in {path}")
    try:
        return validate_calibration_config_data(config, required_sections=())
    except ValueError as exc:
        raise ValueError(f"Invalid calibration configuration in {path}: {exc}") from exc


def resolve_calibration_settings(
    config,
    *,
    model_parameter_order,
):
    """
    Resolve common calibration settings from a validated TOML payload.
    """
    calibration_cfg = config["calibration"]
    method_cfg = config["calibration_method"]
    model_order = tuple(str(name) for name in model_parameter_order)

    objective_metric = str(calibration_cfg["objective_metric"])
    method = str(calibration_cfg["global_method"])
    bounds_raw = dict(config["bounds"])
    bound_names = tuple(bounds_raw.keys())

    missing = [name for name in model_order if name not in bounds_raw]
    extra = [name for name in bound_names if name not in model_order]
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing={missing}")
        if extra:
            details.append(f"extra={extra}")
        details_txt = ", ".join(details)
        raise ValueError(
            "[bounds] must define all model parameters in "
            f"{model_order}. Problem: {details_txt}"
        )

    parameter_set = CalibrationParameterSet.from_bounds(
        bounds_raw,
        parameter_names=model_order,
    )
    parameter_names = parameter_set.names
    bounds = parameter_set.as_bounds_dict()

    method_kwargs_raw = dict(method_cfg.get(method, {}))

    method_kwargs = normalize_format_method_kwargs(
        method=method,
        method_kwargs=method_kwargs_raw,
        parameter_names=parameter_names,
    )

    if method == "da_mh_gp":
        metric_key = objective_metric.strip().lower()
        if metric_key != "rmse":
            warnings.warn(
                "For method 'da_mh_gp', objective_metric is forced to 'rmse' "
                "because the likelihood is defined from RMSE(theta).",
                UserWarning,
                stacklevel=2,
            )
            objective_metric = "rmse"

    return {
        "objective_metric": objective_metric,
        "method": method,
        "bounds": bounds,
        "parameter_names": parameter_names,
        "parameter_set": parameter_set,
        "method_kwargs": method_kwargs,
    }
