"""Configuration contract for the model-calibration launcher."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from hydromodpy.analysis.calibration.core.engine_config import (
    CalibrationSectionSchema,
    ObjectiveSectionSchema,
    resolve_calibration_settings,
)
from hydromodpy.analysis.calibration.core.methods_config import (
    validate_calibration_method_section_or_raise,
)
from hydromodpy.analysis.calibration.core.objective_function import ObjectiveFunction


_SUPPORTED_DETAIL_LEVELS = ("minimal", "diagnostic", "full")
_SUPPORTED_HYDRAULIC_PROPERTIES = ("K", "Sy")


def _validate_bounds_mapping(value: object) -> dict[str, tuple[float, float]]:
    """Normalize one raw [bounds] mapping."""
    if not isinstance(value, Mapping) or not value:
        raise ValueError("[bounds] must be a non-empty mapping")

    parsed: dict[str, tuple[float, float]] = {}
    for raw_name, pair in dict(value).items():
        name = str(raw_name).strip()
        if not name:
            raise ValueError("[bounds] cannot contain empty parameter names")
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"Bounds for '{name}' must be a 2-value list/tuple")
        low = float(pair[0])
        high = float(pair[1])
        if low >= high:
            raise ValueError(f"Invalid bounds for '{name}': lower must be < upper")
        parsed[name] = (low, high)
    return parsed


class ModelCalibrationParameterSchema(BaseModel):
    """One calibrated hydraulic parameter exposed by the launcher."""

    model_config = ConfigDict(extra="forbid")

    name: str
    target: str
    property: str | None = Field(
        default=None,
        description="Optional hydraulic property label ('K' or 'Sy').",
    )
    mode: Literal["replace", "scale"] = "replace"
    parameterization: Literal["global_value", "global_factor", "lithology_value"] = (
        "global_value"
    )

    @field_validator("name", "target")
    @classmethod
    def _validate_required_text(cls, value: object) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("value cannot be empty")
        return text

    @field_validator("property")
    @classmethod
    def _validate_optional_property(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if text not in _SUPPORTED_HYDRAULIC_PROPERTIES:
            raise ValueError(
                "model_calibration.parameter.property must be one of "
                f"{_SUPPORTED_HYDRAULIC_PROPERTIES}"
            )
        return text


class ModelCalibrationOutputSchema(BaseModel):
    """One observable extraction request declared in the launcher config."""

    model_config = ConfigDict(extra="forbid")

    name: str
    variable: str
    source: Literal["runtime", "postprocess", "disk"] = "runtime"
    support: Literal["point", "boundary", "cell_mask", "map"] = "point"
    x: float | None = None
    y: float | None = None
    boundary_id: str | None = None
    time: str | None = None
    time_window: tuple[str, str] | None = None
    time_reducer: str | None = None
    reducer: str | None = None
    comparison: str | None = None
    threshold: float | None = None
    observed_values: list[float] | None = None

    @field_validator("name", "variable")
    @classmethod
    def _validate_required_text(cls, value: object) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("value cannot be empty")
        return text

    @field_validator("boundary_id", "time", "time_reducer", "reducer", "comparison")
    @classmethod
    def _validate_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("optional text value cannot be empty")
        return text

    @field_validator("observed_values")
    @classmethod
    def _validate_observed_values(cls, value: object) -> list[float] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not value:
            raise ValueError("observed_values must be a non-empty numeric list")
        return [float(item) for item in value]

    @model_validator(mode="after")
    def _validate_support_specific_fields(self) -> "ModelCalibrationOutputSchema":
        if self.time is not None and self.time_window is not None:
            raise ValueError(
                "model_calibration.output cannot declare both time and time_window"
            )
        if self.time is None and self.time_window is None:
            self.time = "all"

        if self.support == "point":
            if self.x is None or self.y is None:
                raise ValueError(
                    "point outputs require x and y coordinates"
                )
            if self.reducer is None:
                self.reducer = "weighted_interpolation"
        elif self.support == "boundary":
            if self.boundary_id is None:
                raise ValueError(
                    "boundary outputs require boundary_id"
                )
            if self.reducer is None:
                self.reducer = "sum"
        elif self.support == "cell_mask":
            if self.reducer is None:
                self.reducer = "sum"
        elif self.support == "map":
            if self.reducer is None:
                self.reducer = "identity"

        return self


class ModelCalibrationObjectiveBlockSchema(BaseModel):
    """One weighted block contributing to the composite objective."""

    model_config = ConfigDict(extra="forbid")

    name: str
    metric: str = "rmse"
    weight: float = 1.0
    uses_outputs: list[str]
    normalize_cost: bool = True

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value: object) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("objective block name cannot be empty")
        return text

    @field_validator("metric")
    @classmethod
    def _validate_metric(cls, value: object) -> str:
        text = str(value).strip().lower()
        if text == "direct_cost":
            return text
        return ObjectiveFunction.resolve_metric_name(text)

    @field_validator("weight")
    @classmethod
    def _validate_weight(cls, value: object) -> float:
        weight = float(value)
        if weight <= 0.0:
            raise ValueError("objective block weight must be > 0")
        return weight

    @field_validator("uses_outputs")
    @classmethod
    def _validate_uses_outputs(cls, value: object) -> list[str]:
        if not isinstance(value, list) or not value:
            raise ValueError("uses_outputs must be a non-empty list")
        outputs = [str(item).strip() for item in value]
        if any(not item for item in outputs):
            raise ValueError("uses_outputs cannot contain empty names")
        if len(set(outputs)) != len(outputs):
            raise ValueError("uses_outputs cannot contain duplicates")
        return outputs


class ModelCalibrationSectionSchema(BaseModel):
    """Launcher-owned section controlling calibration orchestration."""

    model_config = ConfigDict(extra="forbid")

    simulation_config: str
    calibration_id: str | None = None
    disable_display: bool = True
    disable_postprocess: bool = True
    rerun_best_with_outputs: bool = True
    persist_iteration_history: bool = True
    persist_iteration_detail_level: str = "minimal"
    parameter: list[ModelCalibrationParameterSchema] = Field(default_factory=list)
    output: list[ModelCalibrationOutputSchema] = Field(default_factory=list)
    objective_block: list[ModelCalibrationObjectiveBlockSchema] = Field(
        default_factory=list
    )

    @field_validator("simulation_config", "calibration_id")
    @classmethod
    def _validate_optional_text(cls, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("text value cannot be empty")
        return text

    @field_validator("persist_iteration_detail_level")
    @classmethod
    def _validate_detail_level(cls, value: object) -> str:
        text = str(value).strip().lower()
        if text not in _SUPPORTED_DETAIL_LEVELS:
            raise ValueError(
                "persist_iteration_detail_level must be one of "
                f"{_SUPPORTED_DETAIL_LEVELS}"
            )
        return text

    @model_validator(mode="after")
    def _validate_non_empty_lists(self) -> "ModelCalibrationSectionSchema":
        if not self.parameter:
            raise ValueError("model_calibration.parameter must contain at least one item")
        if not self.output:
            raise ValueError("model_calibration.output must contain at least one item")
        if not self.objective_block:
            raise ValueError(
                "model_calibration.objective_block must contain at least one item"
            )
        return self


class ModelCalibrationConfig(BaseModel):
    """Validated top-level configuration for the model-calibration launcher."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    calibration: CalibrationSectionSchema = Field(default_factory=CalibrationSectionSchema)
    bounds: dict[str, tuple[float, float]]
    calibration_method: dict[str, dict[str, Any]] = Field(default_factory=dict)
    objective: ObjectiveSectionSchema = Field(default_factory=ObjectiveSectionSchema)
    model_calibration: ModelCalibrationSectionSchema
    simulation_config_path: Path

    _raw_toml: dict[str, Any] = {}

    @classmethod
    def from_toml(
        cls,
        raw_toml: Mapping[str, Any],
        *,
        base_dir: Path,
    ) -> "ModelCalibrationConfig":
        """Validate one raw TOML payload and resolve relative paths."""
        if not isinstance(raw_toml, Mapping):
            raise ValueError("configuration must be a mapping")

        raw_dict = dict(raw_toml)
        if "model_calibration" not in raw_dict:
            raise KeyError("Missing required section 'model_calibration'")
        if "bounds" not in raw_dict:
            raise KeyError("Missing required section 'bounds'")

        model_calibration = ModelCalibrationSectionSchema.model_validate(
            raw_dict["model_calibration"]
        )
        bounds = _validate_bounds_mapping(raw_dict["bounds"])
        calibration_method = validate_calibration_method_section_or_raise(
            raw_dict.get("calibration_method", {})
        )
        objective = ObjectiveSectionSchema.model_validate(raw_dict.get("objective", {}))
        calibration = CalibrationSectionSchema.model_validate(
            raw_dict.get("calibration", {})
        )

        simulation_config_path = Path(model_calibration.simulation_config).expanduser()
        if not simulation_config_path.is_absolute():
            simulation_config_path = (base_dir / simulation_config_path).resolve()
        else:
            simulation_config_path = simulation_config_path.resolve()

        cfg = cls(
            calibration=calibration,
            bounds=bounds,
            calibration_method=calibration_method,
            objective=objective,
            model_calibration=model_calibration,
            simulation_config_path=simulation_config_path,
        )
        cfg._raw_toml = dict(raw_dict)
        return cfg

    @model_validator(mode="after")
    def _validate_cross_section_consistency(self) -> "ModelCalibrationConfig":
        parameter_names = self.parameter_names
        bound_names = tuple(self.bounds.keys())
        if parameter_names != bound_names:
            missing = [name for name in parameter_names if name not in self.bounds]
            extra = [name for name in bound_names if name not in parameter_names]
            details: list[str] = []
            if missing:
                details.append(f"missing={missing}")
            if extra:
                details.append(f"extra={extra}")
            raise ValueError(
                "[bounds] must define exactly the declared "
                f"model_calibration.parameter names in the same order. Problem: "
                f"{', '.join(details)}"
            )

        if len(set(parameter_names)) != len(parameter_names):
            raise ValueError("model_calibration.parameter names must be unique")

        output_names = self.output_names
        if len(set(output_names)) != len(output_names):
            raise ValueError("model_calibration.output names must be unique")

        block_names = self.objective_block_names
        if len(set(block_names)) != len(block_names):
            raise ValueError("model_calibration.objective_block names must be unique")

        output_name_set = set(output_names)
        for block in self.model_calibration.objective_block:
            unknown = [name for name in block.uses_outputs if name not in output_name_set]
            if unknown:
                raise ValueError(
                    f"objective block '{block.name}' references unknown outputs: {unknown}"
                )

        return self

    @property
    def parameter_names(self) -> tuple[str, ...]:
        """Ordered calibrated parameter names."""
        return tuple(item.name for item in self.model_calibration.parameter)

    @property
    def output_names(self) -> tuple[str, ...]:
        """Ordered observable output names."""
        return tuple(item.name for item in self.model_calibration.output)

    @property
    def objective_block_names(self) -> tuple[str, ...]:
        """Ordered composite objective block names."""
        return tuple(item.name for item in self.model_calibration.objective_block)

    def resolve_core_settings(self) -> dict[str, Any]:
        """Adapt launcher config to the existing calibration core settings contract."""
        return resolve_calibration_settings(
            {
                "calibration": self.calibration.model_dump(mode="python"),
                "bounds": dict(self.bounds),
                "calibration_method": dict(self.calibration_method),
                "objective": self.objective.model_dump(mode="python"),
            },
            model_parameter_order=self.parameter_names,
        )


__all__ = (
    "ModelCalibrationConfig",
    "ModelCalibrationObjectiveBlockSchema",
    "ModelCalibrationOutputSchema",
    "ModelCalibrationParameterSchema",
    "ModelCalibrationSectionSchema",
)
