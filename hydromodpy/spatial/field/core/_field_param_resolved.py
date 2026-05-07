"""Resolved field-parameter schema and validator.

`ResolvedFieldParam` is the merged mapping consumed by `FieldParam.from_dict`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import (
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.spatial.field.core._field_param_sections import (
    FieldKind,
    FieldVerticalProfileSection,
    HeterogeneousValueSource,
)
from hydromodpy.spatial.field.core._field_param_units import normalize_unit_token


class ResolvedFieldParam(HydroModelBase):
    """Schema for a fully resolved field-parameter payload."""

    id: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Resolved parameter identifier.",
    )
    kind: Annotated[FieldKind | None, Profile.DEV] = Field(
        default=None,
        description="Resolved parameter kind: homogeneous or heterogeneous.",
    )
    unit: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Resolved parameter unit (canonical token).",
    )
    value: Annotated[object | None, Profile.DEV] = Field(
        default=None,
        description="Resolved scalar value for homogeneous kind.",
    )
    values: Annotated[dict[str, float | str] | None, Profile.DEV] = Field(
        default=None,
        description="Resolved mapping for heterogeneous kind.",
    )
    field_spatial_id: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Resolved spatial field identifier for heterogeneous kind.",
    )
    values_source: Annotated[HeterogeneousValueSource | None, Profile.DEV] = Field(
        default=None,
        description="Optional helper flag describing heterogeneous values source.",
    )
    values_csv_file: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Optional helper CSV path used before resolution.",
    )
    csv_key_column: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Optional helper CSV key column used before resolution.",
    )
    csv_value_column: Annotated[str | None, Profile.DEV] = Field(
        default=None,
        description="Optional helper CSV value column used before resolution.",
    )
    vertical_profile: Annotated[FieldVerticalProfileSection | None, Profile.DEV] = Field(
        default=None,
        description="Resolved optional depth profile configuration.",
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("id cannot be empty")
        return text

    @field_validator("unit")
    @classmethod
    def _validate_unit(cls, value):
        return normalize_unit_token(value)

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value):
        if value is None:
            return None
        if isinstance(value, bool):
            raise TypeError("value must be numeric or '<number> <unit>'")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            token = value.strip()
            if token == "":
                raise ValueError("value cannot be empty")
            return token
        raise TypeError("value must be numeric or '<number> <unit>'")

    @field_validator("values", mode="before")
    @classmethod
    def _validate_values(cls, value):
        if value is None:
            return None
        values: dict[str, float | str] = {}
        for key, raw_value in dict(value).items():
            key_text = str(key)
            if isinstance(raw_value, bool):
                raise TypeError(f"values['{key_text}'] must be numeric or '<number> <unit>'")
            if isinstance(raw_value, (int, float)):
                values[key_text] = float(raw_value)
                continue
            if isinstance(raw_value, str):
                token = raw_value.strip()
                if token == "":
                    raise ValueError(f"values['{key_text}'] cannot be empty")
                values[key_text] = token
                continue
            raise TypeError(f"values['{key_text}'] must be numeric or '<number> <unit>'")
        if len(values) == 0:
            raise ValueError("values cannot be empty")
        if any(str(key).strip() == "" for key in values):
            raise ValueError("values cannot contain empty keys")
        return values

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
            if self.values is not None:
                self.values = None
            if self.field_spatial_id is not None:
                self.field_spatial_id = None
            return self

        if self.values is None:
            raise ValueError("Heterogeneous field requires 'values'")
        if self.field_spatial_id is None:
            raise ValueError("Heterogeneous field requires 'field_spatial_id'")
        if self.value is not None:
            self.value = None
        return self


def validate_resolved_field_param_data(
    config_data: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate merged field-parameter mapping before building `FieldParam`."""
    if not isinstance(config_data, Mapping):
        raise ValueError("resolved field parameter payload must be a mapping")

    payload = dict(config_data)
    if "vertical_profile" not in payload and "field_vertical_profile" in payload:
        payload["vertical_profile"] = payload["field_vertical_profile"]
    payload.pop("field_vertical_profile", None)

    if payload.get("id") is None:
        raise KeyError("Missing required key 'id'")
    if payload.get("kind") is None:
        raise KeyError("Missing required key 'kind'")

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
        parsed = ResolvedFieldParam.model_validate(payload)
    except (ValidationError, TypeError) as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python", exclude_none=True)
