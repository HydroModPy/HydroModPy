"""Field-parameter TOML payloads: their Pydantic schema, their resolution and its check.

A payload is resolved into one canonical mapping, `ResolvedFieldParam`, which
`FieldParam.from_dict` consumes.
"""

from __future__ import annotations

import csv
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, cast

from pydantic import (
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import NonEmptyPath, NonEmptyStr
from hydromodpy.spatial.field.field_param_sections import (
    FieldBaseSection,
    FieldHeterogeneousSection,
    FieldHomogeneousSection,
    FieldKind,
    FieldSection,
    FieldVerticalProfileSection,
    HeterogeneousValueSource,
    VerticalProfileInterpolation,
    VerticalProfileMode,
    coerce_scalar_value_with_unit,
    coerce_value_with_declared_unit,
    normalize_value,
    normalize_values,
)
from hydromodpy.spatial.field.field_param_units import SUPPORTED_PARAMETER_UNITS, UnitStr


class ResolvedFieldParam(HydroModelBase):
    """Schema for a fully resolved field-parameter payload."""

    id: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description="Resolved parameter identifier.",
    )
    kind: Annotated[FieldKind | None, Profile.DEV] = Field(
        default=None,
        description="Resolved parameter kind: homogeneous or heterogeneous.",
    )
    unit: Annotated[UnitStr, Profile.DEV] = Field(
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
    field_spatial_id: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description="Resolved spatial field identifier for heterogeneous kind.",
    )
    values_source: Annotated[HeterogeneousValueSource | None, Profile.DEV] = Field(
        default=None,
        description="Optional helper flag describing heterogeneous values source.",
    )
    values_csv_file: Annotated[NonEmptyPath | None, Profile.DEV] = Field(
        default=None,
        description="Optional helper CSV path used before resolution.",
    )
    csv_key_column: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description="Optional helper CSV key column used before resolution.",
    )
    csv_value_column: Annotated[NonEmptyStr | None, Profile.DEV] = Field(
        default=None,
        description="Optional helper CSV value column used before resolution.",
    )
    vertical_profile: Annotated[FieldVerticalProfileSection | None, Profile.DEV] = Field(
        default=None,
        description="Resolved optional depth profile configuration.",
    )

    @field_validator("value")
    @classmethod
    def _validate_value(cls, value):
        return None if value is None else normalize_value(value, label="value")

    @field_validator("values", mode="before")
    @classmethod
    def _validate_values(cls, value):
        return normalize_values(value, label="values")

    @model_validator(mode="after")
    def _coerce_value_with_declared_unit(self):
        return coerce_value_with_declared_unit(self)

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


def resolve_relative_to(path_like: str | Path, *, base_dir: Path) -> Path:
    """Resolve one path relative to a base directory if not absolute."""
    raw = Path(str(path_like))
    if raw.is_absolute():
        return raw
    return (base_dir / raw).resolve()


def load_values_mapping_csv(
    csv_path: str | Path,
    *,
    key_column: str = "zone_key",
    value_column: str = "value",
) -> dict[str, float]:
    """Load one heterogeneous key->value mapping from CSV."""
    key_col = str(key_column).strip()
    val_col = str(value_column).strip()
    if key_col == "" or val_col == "":
        raise ValueError("CSV key/value column names cannot be empty")

    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"CSV values file not found: {path}")

    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        headers = [str(h).strip() for h in (reader.fieldnames or [])]
        if key_col not in headers:
            raise KeyError(
                f"CSV values file '{path}' is missing key column '{key_col}'. "
                f"Available columns: {headers}"
            )
        if val_col not in headers:
            raise KeyError(
                f"CSV values file '{path}' is missing value column '{val_col}'. "
                f"Available columns: {headers}"
            )

        values: dict[str, float] = {}
        for i, row in enumerate(reader, start=2):  # 1=header
            key_raw = row.get(key_col, "")
            key = str(key_raw).strip()
            if key == "":
                continue
            if key in values:
                raise ValueError(f"Duplicate key '{key}' in CSV mapping '{path}' at line {i}.")
            raw_value = row.get(val_col, "")
            try:
                value = float(raw_value)
            except Exception as exc:
                raise ValueError(
                    f"Invalid numeric value in CSV mapping '{path}' line {i}: "
                    f"column '{val_col}' -> {raw_value!r}"
                ) from exc
            values[key] = value

    if len(values) == 0:
        raise ValueError(f"CSV values file '{path}' does not define any key/value pair")
    return values


def resolve_field_param_config_payload(
    config_data: Mapping[str, Any],
    *,
    param_id: str | None = None,
    base_dir: Path | None = None,
    section_label: str = "field",
) -> dict[str, Any]:
    """Resolve one field-parameter TOML-like payload into canonical mapping."""

    validated = validate_field_param_toml_data(config_data)

    field_section = validated.get("field")
    if not isinstance(field_section, Mapping):
        raise KeyError(f"{section_label} requires section [{section_label}.field]")

    merged: dict[str, Any] = dict(field_section)
    field_id = str(merged.get("id", "")).strip()
    if param_id is not None:
        if field_id == "":
            merged["id"] = param_id
        elif field_id != param_id:
            raise ValueError(
                f"{section_label}.field.id must match section key '{param_id}', got '{field_id}'"
            )

    kind_raw = merged.get("kind")
    kind_key = str(kind_raw).strip().lower() if kind_raw is not None else None

    vertical_section = validated.get("field_vertical_profile", validated.get("vertical_profile"))
    if isinstance(vertical_section, Mapping):
        merged["vertical_profile"] = dict(vertical_section)

    if kind_key == "heterogeneous":
        value_source = str(merged.get("values_source", "inline")).strip().lower()
        if value_source == "csv":
            csv_file = merged.get("values_csv_file")
            if csv_file is None or str(csv_file).strip() == "":
                raise KeyError(
                    "Heterogeneous field with values_source='csv' requires 'values_csv_file'"
                )
            if base_dir is None:
                raise ValueError(
                    "CSV heterogeneous payload requires 'base_dir' to resolve values_csv_file"
                )
            csv_path = resolve_relative_to(csv_file, base_dir=base_dir)
            csv_key_column = str(merged.get("csv_key_column", "zone_key"))
            csv_value_column = str(merged.get("csv_value_column", "value"))
            merged["values"] = load_values_mapping_csv(
                csv_path,
                key_column=csv_key_column,
                value_column=csv_value_column,
            )

    for helper_key in (
        "values_source",
        "values_csv_file",
        "csv_key_column",
        "csv_value_column",
    ):
        merged.pop(helper_key, None)

    return validate_resolved_field_param_data(merged)


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
        """Validate every value the section writes against ``PHYSICAL_BOUNDS``, in its declared unit.

        A homogeneous value and each inline zone value are checked here. A value
        written ``"<number> <unit>"`` is checked in that unit. A section with no
        ``id`` and a CSV table are checked by ``FieldParam``, once the id and the
        values are known.
        """
        from hydromodpy.core.units.physical_bounds import validate_physical_value

        field = self.field
        if field.id is None:
            return self
        if isinstance(field, FieldHomogeneousSection):
            if field.value is not None:
                validate_physical_value(
                    param_id=field.id, value=cast(float, field.value), unit=field.unit
                )
            return self
        for zone_key, raw_value in (field.values or {}).items():
            value, unit = raw_value, field.unit
            if isinstance(raw_value, str):
                value, unit = coerce_scalar_value_with_unit(
                    raw_value, field.unit, location=f"{field.id}.values[{zone_key}]"
                )
            validate_physical_value(
                param_id=field.id, value=float(value), unit=unit, where=f"zone {zone_key!r}"
            )
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
