"""Pydantic schemas and helpers for field parameter TOML payloads."""

from __future__ import annotations

import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any

from pydantic import (
    Field,
    ValidationError,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.spatial.field.core._field_param_resolution import (
    resolve_field_param_config_payload,
)
from hydromodpy.spatial.field.core._field_param_resolved import (
    ResolvedFieldParam,
    validate_resolved_field_param_data,
)
from hydromodpy.spatial.field.core._field_param_sections import (
    FieldBaseSection,
    FieldHeterogeneousSection,
    FieldHomogeneousSection,
    FieldKind,
    FieldSection,
    FieldVerticalProfileSection,
    HeterogeneousValueSource,
    VerticalProfileInterpolation,
    VerticalProfileMode,
)
from hydromodpy.spatial.field.core._field_param_units import (
    SUPPORTED_PARAMETER_UNITS,
)

__all__ = (
    "FieldBaseSection",
    "FieldHeterogeneousSection",
    "FieldHomogeneousSection",
    "FieldKind",
    "FieldParamConfig",
    "FieldSection",
    "FieldVerticalProfileSection",
    "HeterogeneousValueSource",
    "ResolvedFieldParam",
    "SUPPORTED_PARAMETER_UNITS",
    "VerticalProfileInterpolation",
    "VerticalProfileMode",
    "load_field_param_toml",
    "resolve_field_param_config_payload",
    "validate_field_param_toml_data",
    "validate_resolved_field_param_data",
)


class FieldParamConfig(HydroModelBase):
    """Top-level schema for field-parameter TOML files."""

    field: Annotated[FieldSection, Profile.USER] = Field(
        ...,
        description="Discriminated parameter section `[field]`.",
    )
    field_vertical_profile: Annotated[FieldVerticalProfileSection | None, Profile.USER] = Field(
        default=None,
        description="Optional depth profile section `[field_vertical_profile]`.",
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_field_common(cls, data):
        if not isinstance(data, Mapping):
            return data
        for key in ("field_common", "field_homogeneous", "field_heterogeneous"):
            if key in data:
                raise ValueError(f"`[{key}]` is no longer supported. Move keys to `[field]`.")
        return data

    @model_validator(mode="after")
    def _enforce_physical_bounds(self) -> FieldParamConfig:
        """Validate homogeneous scalar values against ``PHYSICAL_BOUNDS``.

        Only numeric scalars are checked here; string payloads carry their
        own unit and are handled by lower-level unit resolution.
        """
        from hydromodpy.spatial.field.core.physical_bounds import (
            validate_physical_value,
        )

        if (
            not isinstance(self.field, FieldHomogeneousSection)
            or self.field.id is None
            or self.field.value is None
        ):
            return self
        if isinstance(self.field.value, (int, float)) and not isinstance(self.field.value, bool):
            validate_physical_value(param_id=self.field.id, value=float(self.field.value))
        return self


def validate_field_param_toml_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """Validate raw field-parameter TOML payload and return normalized dictionary."""
    if not isinstance(config_data, Mapping):
        raise ValueError("field parameter configuration must be a mapping")
    try:
        parsed = FieldParamConfig.model_validate(dict(config_data))
    except (ValidationError, TypeError) as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python", exclude_none=True)


def load_field_param_toml(config_path: str | Path) -> dict[str, Any]:
    """Load and validate a field-parameter TOML file."""
    path = Path(config_path)
    with path.open("rb") as stream:
        payload = tomllib.load(stream)
    try:
        return validate_field_param_toml_data(payload)
    except ValueError as exc:
        raise ValueError(f"Invalid field parameter configuration in {path}: {exc}") from exc
