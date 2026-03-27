"""
Pydantic schemas and helpers for calibration TOML payloads.

How Pydantic is used in this module
-----------------------------------
1) Parse raw dictionaries with `model_validate(...)` into typed models.
2) Enforce strict inputs with `ConfigDict(extra="forbid")` so unknown keys fail
   fast instead of being silently ignored.
3) Normalize values in `@field_validator` methods (for example canonical
   method names and metric names).
4) Convert validated models back to regular Python dictionaries with
   `model_dump(mode="python")` so the rest of the calibration code stays
   framework-agnostic.
"""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any, Mapping
import warnings

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from hydromodpy.analysis.calibration.core.parameters import CalibrationParameterSet
from hydromodpy.analysis.calibration.core.objective_function import ObjectiveFunction
from hydromodpy.analysis.calibration.core.objective_transformations import normalize_transform_name
from hydromodpy.analysis.calibration.core.methods_config import (
    is_supported_method,
    normalize_format_method_kwargs,
    validate_calibration_method_section_or_raise,
)


class CalibrationSectionSchema(BaseModel):
    """
    Typed schema for the generic `[calibration]` TOML section.

    Pydantic converts/coerces values to declared types and then validators
    enforce domain rules (supported metric, supported method, non-empty names).
    """

    # Strict mode: any undeclared key in `[calibration]` raises an error.
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


class OutputSectionSchema(BaseModel):
    """
    Typed schema for optional `[output]` plotting/reporting settings.

    Objective-surface approximation is available only when calibrating:
    - 1 parameter (line plot), or
    - 2 parameters (2D colormap).
    It is automatically disabled for 3+ parameters.
    """

    model_config = ConfigDict(extra="forbid")

    output_dir: str = "outputs"
    show_plot: bool = True
    figure_name: str | None = None
    show_objective_surface: bool = False
    objective_surface_n_evaluations: int = 300
    objective_surface_seed: int = 42

    @field_validator("output_dir")
    @classmethod
    def _validate_output_dir(cls, value):
        text = str(value).strip()
        if not text:
            raise ValueError("output_dir cannot be empty")
        return text

    @field_validator("figure_name")
    @classmethod
    def _validate_optional_figure_name(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("figure_name cannot be empty when provided")
        return text

    @field_validator("objective_surface_n_evaluations")
    @classmethod
    def _validate_objective_surface_n_evaluations(cls, value):
        out = int(value)
        if out <= 0:
            raise ValueError("objective_surface_n_evaluations must be > 0")
        return out

    @field_validator("objective_surface_seed")
    @classmethod
    def _validate_objective_surface_seed(cls, value):
        return int(value)


class ObjectiveSectionSchema(BaseModel):
    """
    Typed schema for optional `[objective]` transformation settings.

    This section controls pre-metric transformations applied to both observed
    and simulated series before objective evaluation.
    """

    model_config = ConfigDict(extra="forbid")

    transform: str = "identity"
    transform_params: dict[str, float] = Field(default_factory=dict)

    @field_validator("transform")
    @classmethod
    def _validate_transform(cls, value):
        return normalize_transform_name(value)

    @field_validator("transform_params")
    @classmethod
    def _validate_transform_params_mapping(cls, value):
        if not isinstance(value, Mapping):
            raise ValueError("transform_params must be a mapping")
        out: dict[str, float] = {}
        for raw_key, raw_value in dict(value).items():
            key = str(raw_key).strip()
            if not key:
                raise ValueError("transform_params keys cannot be empty")
            if not isinstance(raw_value, (int, float)):
                raise ValueError("transform_params values must be numeric")
            out[key] = float(raw_value)
        return out

    @model_validator(mode="after")
    def _validate_transform_params_against_transform(self):
        allowed_keys = {
            "identity": frozenset(),
            "sqrt": frozenset(),
            "log": frozenset({"epsilon"}),
            "inverse": frozenset({"epsilon"}),
            "box_cox": frozenset({"lambda_param"}),
        }
        params = dict(self.transform_params)
        keys = set(params.keys())
        allowed = allowed_keys[self.transform]
        extra = sorted(keys - allowed)
        if extra:
            raise ValueError(
                f"Unsupported transform_params for transform '{self.transform}': {extra}. "
                f"Allowed keys: {sorted(allowed)}"
            )
        if self.transform in {"log", "inverse"} and "epsilon" in params:
            if params["epsilon"] <= 0.0:
                raise ValueError("transform_params.epsilon must be > 0")
        return self


class CalibrationTomlSchema(BaseModel):
    """
    Top-level schema shared by calibration examples.

    This model validates common sections before case-specific logic runs.
    """

    # Strict mode at top level as well: unknown sections are rejected.
    model_config = ConfigDict(extra="forbid")

    chronicle: dict[str, Any]
    calibration: CalibrationSectionSchema
    bounds: dict[str, tuple[float, float] | list[float]]
    calibration_method: dict[str, dict[str, Any]] = Field(default_factory=dict)
    output: OutputSectionSchema = Field(default_factory=OutputSectionSchema)
    objective: ObjectiveSectionSchema = Field(default_factory=ObjectiveSectionSchema)

    @field_validator("chronicle")
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

    @model_validator(mode="after")
    def _normalize_output_objective_surface_by_dimension(self):
        """
        Disable objective-surface approximation for 3+ calibrated parameters.
        """
        n_params = len(self.bounds)
        if self.output.show_objective_surface and n_params >= 3:
            warnings.warn(
                "output.show_objective_surface is disabled because objective "
                "surface plotting is supported only for 1D/2D parameter spaces "
                f"(got n_parameters={n_params}).",
                UserWarning,
                stacklevel=2,
            )
            self.output.show_objective_surface = False
        return self


def validate_calibration_config_data(
    config_data: Mapping[str, Any],
    *,
    required_sections: tuple[str, ...] = (),
) -> dict[str, Any]:
    """
    Validate raw configuration and return a normalized Python dictionary.

    Notes
    -----
    `CalibrationTomlSchema.model_validate(...)` is the main Pydantic entry
    point. It applies type parsing and all validators declared above.
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
    Load TOML file and run schema validation.

    The returned payload is already normalized (typed values, canonical method
    names, validated bounds) and safe to consume downstream.
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
    Resolve calibration settings from a validated configuration payload.

    The input is expected to come from `load_calibration_toml(...)`, so this
    function focuses on cross-section consistency checks and final adaptation
    to engine-ready objects.
    """
    calibration_cfg = config["calibration"]
    method_cfg = config["calibration_method"]
    objective_cfg = dict(
        config.get(
            "objective",
            {
                "transform": "identity",
                "transform_params": {},
            },
        )
    )
    objective_cfg = ObjectiveSectionSchema.model_validate(objective_cfg).model_dump(
        mode="python"
    )
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

    # Extract only the kwargs block for the selected method.
    method_kwargs_raw = dict(method_cfg.get(method, {}))

    # Delegate method-specific schema validation and normalization.
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
        "objective": objective_cfg,
        "method": method,
        "bounds": bounds,
        "parameter_names": parameter_names,
        "parameter_set": parameter_set,
        "method_kwargs": method_kwargs,
    }

