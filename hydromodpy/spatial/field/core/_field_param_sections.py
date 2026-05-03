"""Pydantic schemas for field-parameter TOML sections.

Models cover the four sub-sections of `field_param_config.toml`:
- `[field]` base section,
- `[field_homogeneous]`,
- `[field_heterogeneous]`,
- `[field_vertical_profile]`.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal

from pydantic import (
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.units import Length
from hydromodpy.spatial.field.core._field_param_units import normalize_unit_token

FieldKind = Literal["homogeneous", "heterogeneous"]
HeterogeneousValueSource = Literal["inline", "csv"]
VerticalProfileMode = Literal["none", "exponential", "tabulated"]
VerticalProfileInterpolation = Literal["linear", "step"]


class FieldBaseSection(HydroModelBase):
    """Schema for `[field]` base section."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=("Parameter identifier used in outputs and logs (for example 'K', 'Sy')."),
    )
    kind: Annotated[FieldKind | None, Profile.USER] = Field(
        default=None,
        description=("Field type selector. Allowed values: 'homogeneous' or 'heterogeneous'."),
    )
    unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Unit of parameter values. Typical examples: 'm/s' (K), '-' (Sy), 'm-1' (Ss)."
        ),
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("field.id cannot be empty")
        return text

    @field_validator("unit")
    @classmethod
    def _validate_unit(cls, value):
        return normalize_unit_token(value)


class FieldHomogeneousSection(HydroModelBase):
    """Schema for `[field_homogeneous]`."""

    model_config = ConfigDict(extra="forbid")

    value: Annotated[object | None, Profile.USER] = Field(
        default=None,
        description="Scalar surface value used when kind='homogeneous'.",
    )

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value):
        if value is None:
            return None
        if isinstance(value, bool):
            raise TypeError("field_homogeneous.value must be numeric or '<number> <unit>'")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            token = value.strip()
            if token == "":
                raise ValueError("field_homogeneous.value cannot be empty")
            return token
        raise TypeError("field_homogeneous.value must be numeric or '<number> <unit>'")


class FieldHeterogeneousSection(HydroModelBase):
    """Schema for `[field_heterogeneous]`."""

    model_config = ConfigDict(extra="forbid")

    values_source: Annotated[HeterogeneousValueSource, Profile.USER] = Field(
        default="inline",
        description=(
            "Source for heterogeneous values. "
            "Use 'inline' for TOML mapping or 'csv' for external table."
        ),
    )
    values: Annotated[dict[str, object] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Inline key/value mapping used when values_source='inline'. "
            "Keys are zone/material ids, values are numeric parameter values."
        ),
    )
    values_csv_file: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description=(
            "Path to CSV mapping file used when values_source='csv'. "
            "Relative paths are resolved from TOML directory."
        ),
    )
    csv_key_column: Annotated[str, Profile.DEV] = Field(
        default="zone_key",
        description="CSV column name containing zone/material keys.",
    )
    csv_value_column: Annotated[str, Profile.DEV] = Field(
        default="value",
        description="CSV column name containing numeric parameter values.",
    )
    field_spatial_id: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Identifier of the spatial field used to map heterogeneous values "
            "(must match geometry field id)."
        ),
    )

    @field_validator("values")
    @classmethod
    def _validate_values(cls, value):
        if value is None:
            return None
        values: dict[str, object] = {}
        for key, raw_value in dict(value).items():
            key_text = str(key)
            if isinstance(raw_value, bool):
                raise TypeError(
                    f"field_heterogeneous.values['{key_text}'] must be numeric or '<number> <unit>'"
                )
            if isinstance(raw_value, (int, float)):
                values[key_text] = float(raw_value)
                continue
            if isinstance(raw_value, str):
                token = raw_value.strip()
                if token == "":
                    raise ValueError(f"field_heterogeneous.values['{key_text}'] cannot be empty")
                values[key_text] = token
                continue
            raise TypeError(
                f"field_heterogeneous.values['{key_text}'] must be numeric or '<number> <unit>'"
            )
        if len(values) == 0:
            raise ValueError("field_heterogeneous.values cannot be empty")
        if any(str(key).strip() == "" for key in values):
            raise ValueError("field_heterogeneous.values cannot contain empty keys")
        return values

    @field_validator("values_csv_file")
    @classmethod
    def _validate_values_csv_file(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("field_heterogeneous.values_csv_file cannot be empty when provided")
        return text

    @field_validator("csv_key_column", "csv_value_column")
    @classmethod
    def _validate_csv_column_names(cls, value):
        text = str(value).strip()
        if text == "":
            raise ValueError("CSV column name cannot be empty")
        return text

    @field_validator("field_spatial_id")
    @classmethod
    def _validate_field_spatial_id(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("field_heterogeneous.field_spatial_id cannot be empty")
        return text

    @model_validator(mode="after")
    def _validate_value_source_payload(self):
        # Allow an empty section so users can keep full templates in TOML
        # even when this heterogeneous block is not the active `field.kind`.
        if (
            self.values is None
            and self.values_csv_file is None
            and self.field_spatial_id is None
            and self.values_source == "inline"
            and self.csv_key_column == "zone_key"
            and self.csv_value_column == "value"
        ):
            return self

        if self.values_source == "inline":
            if self.values is None:
                raise ValueError(
                    "field_heterogeneous.values is required when values_source='inline'"
                )
            if self.field_spatial_id is None:
                raise ValueError(
                    "field_heterogeneous.field_spatial_id is required for heterogeneous mapping"
                )
            return self

        if self.values_source == "csv":
            if self.values_csv_file is None:
                raise ValueError(
                    "field_heterogeneous.values_csv_file is required when values_source='csv'"
                )
            if self.field_spatial_id is None:
                raise ValueError(
                    "field_heterogeneous.field_spatial_id is required for heterogeneous mapping"
                )
            return self

        return self


class FieldVerticalProfileSection(HydroModelBase):
    """Schema for `[field_vertical_profile]`."""

    model_config = ConfigDict(extra="forbid")

    mode: Annotated[VerticalProfileMode, Profile.USER] = Field(
        default="none",
        description=(
            "Depth dependency mode shared over the full domain. "
            "Allowed values: 'none', 'exponential', 'tabulated'."
        ),
    )
    characteristic_depth: Annotated[Length | None, Profile.DEV] = Field(
        default=None,
        gt=0.0,
        description=(
            "Characteristic depth for exponential mode. "
            "Vertical factor is exp(-depth/characteristic_depth)."
        ),
    )
    min_factor: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description=(
            "Optional floor factor for exponential mode. "
            "If provided, factor is max(exp(-depth/characteristic_depth), min_factor)."
        ),
    )
    depths: Annotated[list[float] | None, Profile.DEV] = Field(
        default=None,
        min_length=1,
        description="Depth nodes for tabulated mode (meters, first value must be 0).",
    )
    factors: Annotated[list[float] | None, Profile.DEV] = Field(
        default=None,
        min_length=1,
        description=(
            "Multiplicative factors aligned with `depths` for tabulated mode "
            "(first value must be 1 at depth 0)."
        ),
    )
    interpolation: Annotated[VerticalProfileInterpolation, Profile.DEV] = Field(
        default="linear",
        description=(
            "Interpolation strategy for tabulated mode. Allowed values: 'linear' or 'step'."
        ),
    )

    @model_validator(mode="after")
    def _validate_mode_payload(self):
        if self.mode == "none":
            return self

        if self.mode == "exponential":
            if self.characteristic_depth is None:
                raise ValueError(
                    "field_vertical_profile.characteristic_depth is required when mode='exponential'"
                )
            return self

        if self.mode == "tabulated":
            if self.depths is None:
                raise ValueError("field_vertical_profile.depths is required when mode='tabulated'")
            if self.factors is None:
                raise ValueError("field_vertical_profile.factors is required when mode='tabulated'")
            if len(self.depths) != len(self.factors):
                raise ValueError("field_vertical_profile.depths and factors must have same length")
            if any(v < 0.0 for v in self.depths):
                raise ValueError("field_vertical_profile.depths must be >= 0")
            if any(self.depths[i] <= self.depths[i - 1] for i in range(1, len(self.depths))):
                raise ValueError("field_vertical_profile.depths must be strictly increasing")
            if not math.isclose(float(self.depths[0]), 0.0, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError("field_vertical_profile tabulated first depth must be 0.0")
            if not math.isclose(float(self.factors[0]), 1.0, rel_tol=0.0, abs_tol=1e-12):
                raise ValueError("field_vertical_profile tabulated factor at depth 0.0 must be 1.0")
            return self

        return self
