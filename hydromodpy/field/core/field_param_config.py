"""
Pydantic schemas and helpers for field parameter TOML payloads.

This module validates the structure used by `field_param_config.toml`:
- base section: `[field]` (id, kind),
- optional mode sections: `[field_homogeneous]`, `[field_heterogeneous]`,
- optional vertical section: `[field_vertical_profile]`,
- optional compatibility section: `[field_common]`.
"""

from __future__ import annotations

from pathlib import Path
import math
import tomllib
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator


SUPPORTED_FIELD_KINDS = ("homogeneous", "heterogeneous")
SUPPORTED_HETEROGENEOUS_VALUE_SOURCES = ("inline", "csv")
SUPPORTED_VERTICAL_PROFILE_MODES = ("none", "exponential", "tabulated")
SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS = ("linear", "step")


class FieldBaseSectionSchema(BaseModel):
    """
    Schema for `[field]` base section.

    Notes
    -----
    `extra="allow"` keeps compatibility with legacy payloads where `value` or
    `values` may also be directly placed in `[field]`.
    """

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    kind: str | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("field.id cannot be empty")
        return text

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        if value is None:
            return None
        kind = str(value).strip().lower()
        if kind not in SUPPORTED_FIELD_KINDS:
            allowed = ", ".join(SUPPORTED_FIELD_KINDS)
            raise ValueError(f"Unsupported field.kind '{value}'. Allowed: {allowed}")
        return kind


class FieldCommonSectionSchema(BaseModel):
    """
    Optional compatibility schema for `[field_common]`.
    """

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    kind: str | None = None

    @field_validator("id")
    @classmethod
    def _validate_optional_id(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("field_common.id cannot be empty")
        return text

    @field_validator("kind")
    @classmethod
    def _validate_optional_kind(cls, value):
        if value is None:
            return None
        kind = str(value).strip().lower()
        if kind not in SUPPORTED_FIELD_KINDS:
            allowed = ", ".join(SUPPORTED_FIELD_KINDS)
            raise ValueError(f"Unsupported field_common.kind '{value}'. Allowed: {allowed}")
        return kind


class FieldHomogeneousSectionSchema(BaseModel):
    """
    Schema for `[field_homogeneous]`.
    """

    model_config = ConfigDict(extra="forbid")

    value: float

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value):
        return float(value)


class FieldHeterogeneousSectionSchema(BaseModel):
    """
    Schema for `[field_heterogeneous]`.
    """

    model_config = ConfigDict(extra="forbid")

    values_source: str = "inline"
    values: dict[str, float] | None = None
    values_csv_file: str | None = None
    csv_key_column: str = "zone_key"
    csv_value_column: str = "value"
    field_spatial_id: str

    @field_validator("values_source")
    @classmethod
    def _validate_values_source(cls, value):
        key = str(value).strip().lower()
        if key not in SUPPORTED_HETEROGENEOUS_VALUE_SOURCES:
            allowed = ", ".join(SUPPORTED_HETEROGENEOUS_VALUE_SOURCES)
            raise ValueError(
                f"Unsupported field_heterogeneous.values_source '{value}'. "
                f"Allowed: {allowed}"
            )
        return key

    @field_validator("values")
    @classmethod
    def _validate_values(cls, value):
        if value is None:
            return None
        values = {str(k): float(v) for k, v in dict(value).items()}
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
        text = str(value).strip()
        if not text:
            raise ValueError("field_heterogeneous.field_spatial_id cannot be empty")
        return text

    @model_validator(mode="after")
    def _validate_value_source_payload(self):
        if self.values_source == "inline":
            if self.values is None:
                raise ValueError(
                    "field_heterogeneous.values is required when values_source='inline'"
                )
            return self

        if self.values_source == "csv":
            if self.values_csv_file is None:
                raise ValueError(
                    "field_heterogeneous.values_csv_file is required when values_source='csv'"
                )
            return self

        return self


class FieldVerticalProfileSectionSchema(BaseModel):
    """
    Schema for `[field_vertical_profile]`.
    """

    model_config = ConfigDict(extra="forbid")

    mode: str = "none"
    characteristic_depth: float | None = None
    depths: list[float] | None = None
    factors: list[float] | None = None
    interpolation: str = "linear"

    @field_validator("mode")
    @classmethod
    def _validate_mode(cls, value):
        key = str(value).strip().lower()
        if key not in SUPPORTED_VERTICAL_PROFILE_MODES:
            allowed = ", ".join(SUPPORTED_VERTICAL_PROFILE_MODES)
            raise ValueError(
                f"Unsupported field_vertical_profile.mode '{value}'. Allowed: {allowed}"
            )
        return key

    @field_validator("characteristic_depth")
    @classmethod
    def _validate_characteristic_depth(cls, value):
        if value is None:
            return None
        numeric = float(value)
        if numeric <= 0.0:
            raise ValueError("field_vertical_profile.characteristic_depth must be > 0")
        return numeric

    @field_validator("depths", "factors")
    @classmethod
    def _validate_optional_non_empty_float_list(cls, value):
        if value is None:
            return None
        arr = [float(v) for v in value]
        if len(arr) == 0:
            raise ValueError("field_vertical_profile list cannot be empty")
        return arr

    @field_validator("interpolation")
    @classmethod
    def _validate_interpolation(cls, value):
        key = str(value).strip().lower()
        if key not in SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS:
            allowed = ", ".join(SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS)
            raise ValueError(
                f"Unsupported field_vertical_profile.interpolation '{value}'. "
                f"Allowed: {allowed}"
            )
        return key

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


class FieldParamTomlSchema(BaseModel):
    """
    Top-level schema for field-parameter TOML files.

    Notes
    -----
    `extra="allow"` keeps compatibility with case-specific extra sections.
    """

    model_config = ConfigDict(extra="allow")

    field: FieldBaseSectionSchema | None = None
    field_common: FieldCommonSectionSchema | None = None
    field_homogeneous: FieldHomogeneousSectionSchema | None = None
    field_heterogeneous: FieldHeterogeneousSectionSchema | None = None
    field_vertical_profile: FieldVerticalProfileSectionSchema | None = None


class ResolvedFieldParamSchema(BaseModel):
    """
    Schema for a fully resolved field-parameter payload.

    This corresponds to the merged mapping consumed by `FieldParam.from_dict`.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    kind: str | None = None
    value: float | None = None
    values: dict[str, float] | None = None
    field_spatial_id: str | None = None
    values_source: str | None = None
    values_csv_file: str | None = None
    csv_key_column: str | None = None
    csv_value_column: str | None = None
    vertical_profile: FieldVerticalProfileSectionSchema | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("id cannot be empty")
        return text

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        if value is None:
            return None
        kind = str(value).strip().lower()
        if kind not in SUPPORTED_FIELD_KINDS:
            allowed = ", ".join(SUPPORTED_FIELD_KINDS)
            raise ValueError(f"Unsupported kind '{value}'. Allowed: {allowed}")
        return kind

    @field_validator("values")
    @classmethod
    def _validate_values(cls, value):
        if value is None:
            return None
        values = {str(k): float(v) for k, v in dict(value).items()}
        if len(values) == 0:
            raise ValueError("values cannot be empty")
        if any(str(key).strip() == "" for key in values):
            raise ValueError("values cannot contain empty keys")
        return values

    @field_validator("values_source")
    @classmethod
    def _validate_optional_values_source(cls, value):
        if value is None:
            return None
        key = str(value).strip().lower()
        if key not in SUPPORTED_HETEROGENEOUS_VALUE_SOURCES:
            allowed = ", ".join(SUPPORTED_HETEROGENEOUS_VALUE_SOURCES)
            raise ValueError(f"Unsupported values_source '{value}'. Allowed: {allowed}")
        return key

    @field_validator("values_csv_file", "csv_key_column", "csv_value_column")
    @classmethod
    def _validate_optional_non_empty(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            raise ValueError("value cannot be empty when provided")
        return text

    @field_validator("field_spatial_id")
    @classmethod
    def _validate_optional_field_spatial_id(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("field_spatial_id cannot be empty when provided")
        return text

    @model_validator(mode="after")
    def _validate_by_kind(self):
        if self.kind is None:
            return self
        if self.kind == "homogeneous":
            if self.value is None:
                raise ValueError("Homogeneous field requires 'value'")
            self.values = None
            self.field_spatial_id = None
            return self

        if self.values is None:
            raise ValueError("Heterogeneous field requires 'values'")
        if self.field_spatial_id is None:
            raise ValueError("Heterogeneous field requires 'field_spatial_id'")
        self.value = None
        return self


def validate_field_param_toml_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """
    Validate raw field-parameter TOML payload and return normalized dictionary.
    """
    if not isinstance(config_data, Mapping):
        raise ValueError("field parameter configuration must be a mapping")
    try:
        parsed = FieldParamTomlSchema.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python", exclude_none=True)


def load_field_param_toml(config_path: str | Path) -> dict[str, Any]:
    """
    Load and validate a field-parameter TOML file.
    """
    path = Path(config_path)
    with path.open("rb") as stream:
        payload = tomllib.load(stream)
    try:
        return validate_field_param_toml_data(payload)
    except ValueError as exc:
        raise ValueError(f"Invalid field parameter configuration in {path}: {exc}") from exc


def validate_resolved_field_param_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """
    Validate merged field-parameter mapping before building `FieldParam`.
    """
    if not isinstance(config_data, Mapping):
        raise ValueError("resolved field parameter payload must be a mapping")

    payload = dict(config_data)
    if "id" not in payload and "identifier" in payload:
        payload["id"] = payload["identifier"]
    if "kind" not in payload and "mode" in payload:
        payload["kind"] = payload["mode"]
    if "values" not in payload and "values_by_key" in payload:
        payload["values"] = payload["values_by_key"]
    if "vertical_profile" not in payload and "field_vertical_profile" in payload:
        payload["vertical_profile"] = payload["field_vertical_profile"]

    if payload.get("id") is None:
        raise KeyError("Missing required key 'id' (or alias 'identifier')")
    if payload.get("kind") is None:
        raise KeyError("Missing required key 'kind' (or alias 'mode')")

    kind_key = str(payload["kind"]).strip().lower()
    if kind_key == "homogeneous":
        if "value" not in payload:
            raise KeyError("Homogeneous field requires key 'value'")
    elif kind_key == "heterogeneous":
        if "values" not in payload:
            raise KeyError("Heterogeneous field requires mapping key 'values'")
        if "field_spatial_id" not in payload:
            raise KeyError("Heterogeneous field requires key 'field_spatial_id'")

    try:
        parsed = ResolvedFieldParamSchema.model_validate(payload)
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python", exclude_none=True)
