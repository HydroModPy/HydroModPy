"""
Pydantic schemas and helpers for field parameter TOML payloads.

This module validates the structure used by `field_param_config.toml`:
- base section: `[field]` (id, kind),
- optional mode sections: `[field_homogeneous]`, `[field_heterogeneous]`,
- optional vertical section: `[field_vertical_profile]`.
"""

from __future__ import annotations

import csv
from pathlib import Path
import math
import tomllib
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from hydromodpy.units.hydraulic_conductivity import (
    M_PER_S_CANONICAL_UNITS,
    normalize_m_per_s_unit,
)
from hydromodpy.units.length import parse_length_to_m


SUPPORTED_FIELD_KINDS = ("homogeneous", "heterogeneous")
SUPPORTED_HETEROGENEOUS_VALUE_SOURCES = ("inline", "csv")
SUPPORTED_VERTICAL_PROFILE_MODES = ("none", "exponential", "tabulated")
SUPPORTED_VERTICAL_PROFILE_INTERPOLATIONS = ("linear", "step")
SUPPORTED_PARAMETER_UNITS = ("-", *M_PER_S_CANONICAL_UNITS, "m-1", "cm-1")

_UNIT_ALIASES = {
    "-": "-",
    "1": "-",
    "none": "-",
    "dimensionless": "-",
    "unitless": "-",
    "m-1": "m-1",
    "1/m": "m-1",
    "m^-1": "m-1",
    "cm-1": "cm-1",
    "1/cm": "cm-1",
    "cm^-1": "cm-1",
}


def _normalize_unit_token(value: str | None) -> str | None:
    """Normalize one user unit token to canonical representation."""
    if value is None:
        return None
    token = str(value).strip().lower().replace(" ", "")
    if token == "":
        raise ValueError("field.unit cannot be empty when provided")
    if token in _UNIT_ALIASES:
        return _UNIT_ALIASES[token]
    try:
        return normalize_m_per_s_unit(token)
    except ValueError:
        allowed = ", ".join(SUPPORTED_PARAMETER_UNITS)
        raise ValueError(f"Unsupported field.unit '{value}'. Allowed: {allowed}") from None


class FieldBaseSectionSchema(BaseModel):
    """
    Schema for `[field]` base section.

    Notes
    -----
    `extra="allow"` keeps compatibility with legacy payloads where `value` or
    `values` may also be directly placed in `[field]`.
    """

    model_config = ConfigDict(extra="allow")

    id: str | None = Field(
        default=None,
        description=(
            "Parameter identifier used in outputs and logs "
            "(for example 'K', 'Sy')."
        ),
    )
    kind: str | None = Field(
        default=None,
        description=(
            "Field type selector. Allowed values: 'homogeneous' or 'heterogeneous'."
        ),
    )
    unit: str | None = Field(
        default=None,
        description=(
            "Unit of parameter values. "
            "Typical examples: 'm/s' (K), '-' (Sy), 'm-1' (Ss)."
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

    @field_validator("unit")
    @classmethod
    def _validate_unit(cls, value):
        return _normalize_unit_token(value)


class FieldHomogeneousSectionSchema(BaseModel):
    """
    Schema for `[field_homogeneous]`.
    """

    model_config = ConfigDict(extra="forbid")

    value: object | None = Field(
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


class FieldHeterogeneousSectionSchema(BaseModel):
    """
    Schema for `[field_heterogeneous]`.
    """

    model_config = ConfigDict(extra="forbid")

    values_source: str = Field(
        default="inline",
        description=(
            "Source for heterogeneous values. "
            "Use 'inline' for TOML mapping or 'csv' for external table."
        ),
    )
    values: dict[str, object] | None = Field(
        default=None,
        description=(
            "Inline key/value mapping used when values_source='inline'. "
            "Keys are zone/material ids, values are numeric parameter values."
        ),
    )
    values_csv_file: str | None = Field(
        default=None,
        description=(
            "Path to CSV mapping file used when values_source='csv'. "
            "Relative paths are resolved from TOML directory."
        ),
    )
    csv_key_column: str = Field(
        default="zone_key",
        description="CSV column name containing zone/material keys.",
    )
    csv_value_column: str = Field(
        default="value",
        description="CSV column name containing numeric parameter values.",
    )
    field_spatial_id: str | None = Field(
        default=None,
        description=(
            "Identifier of the spatial field used to map heterogeneous values "
            "(must match geometry field id)."
        ),
    )

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
        values: dict[str, object] = {}
        for key, raw_value in dict(value).items():
            key_text = str(key)
            if isinstance(raw_value, bool):
                raise TypeError(
                    f"field_heterogeneous.values['{key_text}'] must be numeric "
                    "or '<number> <unit>'"
                )
            if isinstance(raw_value, (int, float)):
                values[key_text] = float(raw_value)
                continue
            if isinstance(raw_value, str):
                token = raw_value.strip()
                if token == "":
                    raise ValueError(
                        f"field_heterogeneous.values['{key_text}'] cannot be empty"
                    )
                values[key_text] = token
                continue
            raise TypeError(
                f"field_heterogeneous.values['{key_text}'] must be numeric "
                "or '<number> <unit>'"
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


class FieldVerticalProfileSectionSchema(BaseModel):
    """
    Schema for `[field_vertical_profile]`.
    """

    model_config = ConfigDict(extra="forbid")

    mode: str = Field(
        default="none",
        description=(
            "Depth dependency mode shared over the full domain. "
            "Allowed values: 'none', 'exponential', 'tabulated'."
        ),
    )
    characteristic_depth: float | None = Field(
        default=None,
        description=(
            "Characteristic depth for exponential mode. "
            "Vertical factor is exp(-depth/characteristic_depth)."
        ),
    )
    min_factor: float | None = Field(
        default=None,
        description=(
            "Optional floor factor for exponential mode. "
            "If provided, factor is max(exp(-depth/characteristic_depth), min_factor)."
        ),
    )
    depths: list[float] | None = Field(
        default=None,
        description="Depth nodes for tabulated mode (meters, first value must be 0).",
    )
    factors: list[float] | None = Field(
        default=None,
        description=(
            "Multiplicative factors aligned with `depths` for tabulated mode "
            "(first value must be 1 at depth 0)."
        ),
    )
    interpolation: str = Field(
        default="linear",
        description=(
            "Interpolation strategy for tabulated mode. "
            "Allowed values: 'linear' or 'step'."
        ),
    )

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

    @field_validator("characteristic_depth", mode="before")
    @classmethod
    def _validate_characteristic_depth(cls, value):
        if value is None:
            return None
        numeric = parse_length_to_m(
            value,
            default_unit="m",
            label="field_vertical_profile.characteristic_depth",
        )
        if numeric <= 0.0:
            raise ValueError("field_vertical_profile.characteristic_depth must be > 0")
        return numeric

    @field_validator("min_factor")
    @classmethod
    def _validate_min_factor(cls, value):
        if value is None:
            return None
        numeric = float(value)
        if numeric < 0.0 or numeric > 1.0:
            raise ValueError("field_vertical_profile.min_factor must be in [0, 1]")
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


class FieldParamConfig(BaseModel):
    """
    Top-level schema for field-parameter TOML files.

    Notes
    -----
    `extra="allow"` keeps compatibility with case-specific extra sections.
    """

    model_config = ConfigDict(extra="allow")

    field: FieldBaseSectionSchema | None = Field(
        default=None,
        description="Base section `[field]` with parameter id and kind.",
    )
    field_homogeneous: FieldHomogeneousSectionSchema | None = Field(
        default=None,
        description="Homogeneous parameters section `[field_homogeneous]`.",
    )
    field_heterogeneous: FieldHeterogeneousSectionSchema | None = Field(
        default=None,
        description="Heterogeneous parameters section `[field_heterogeneous]`.",
    )
    field_vertical_profile: FieldVerticalProfileSectionSchema | None = Field(
        default=None,
        description="Optional depth profile section `[field_vertical_profile]`.",
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_field_common(cls, data):
        if isinstance(data, Mapping) and "field_common" in data:
            raise ValueError(
                "`[field_common]` is no longer supported. "
                "Move shared keys to `[field]`."
            )
        return data


class ResolvedFieldParamSchema(BaseModel):
    """
    Schema for a fully resolved field-parameter payload.

    This corresponds to the merged mapping consumed by `FieldParam.from_dict`.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(
        default=None,
        description="Resolved parameter identifier.",
    )
    kind: str | None = Field(
        default=None,
        description="Resolved parameter kind: homogeneous or heterogeneous.",
    )
    unit: str | None = Field(
        default=None,
        description="Resolved parameter unit (canonical token).",
    )
    value: object | None = Field(
        default=None,
        description="Resolved scalar value for homogeneous kind.",
    )
    values: dict[str, object] | None = Field(
        default=None,
        description="Resolved mapping for heterogeneous kind.",
    )
    field_spatial_id: str | None = Field(
        default=None,
        description="Resolved spatial field identifier for heterogeneous kind.",
    )
    values_source: str | None = Field(
        default=None,
        description="Optional helper flag describing heterogeneous values source.",
    )
    values_csv_file: str | None = Field(
        default=None,
        description="Optional helper CSV path used before resolution.",
    )
    csv_key_column: str | None = Field(
        default=None,
        description="Optional helper CSV key column used before resolution.",
    )
    csv_value_column: str | None = Field(
        default=None,
        description="Optional helper CSV value column used before resolution.",
    )
    vertical_profile: FieldVerticalProfileSectionSchema | None = Field(
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

    @field_validator("unit")
    @classmethod
    def _validate_unit(cls, value):
        return _normalize_unit_token(value)

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
                    f"values['{key_text}'] must be numeric or '<number> <unit>'"
                )
            if isinstance(raw_value, (int, float)):
                values[key_text] = float(raw_value)
                continue
            if isinstance(raw_value, str):
                token = raw_value.strip()
                if token == "":
                    raise ValueError(f"values['{key_text}'] cannot be empty")
                values[key_text] = token
                continue
            raise TypeError(
                f"values['{key_text}'] must be numeric or '<number> <unit>'"
            )
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
        parsed = FieldParamConfig.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python", exclude_none=True)


def _resolve_relative_to(path_like: str | Path, *, base_dir: Path) -> Path:
    """Resolve one path relative to a base directory if not absolute."""
    raw = Path(str(path_like))
    if raw.is_absolute():
        return raw
    return (base_dir / raw).resolve()


def _load_values_mapping_csv(
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
                raise ValueError(
                    f"Duplicate key '{key}' in CSV mapping '{path}' at line {i}."
                )
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
    """Resolve one field-parameter TOML-like payload into canonical mapping.

    This function encapsulates mode selection (`homogeneous`/`heterogeneous`),
    optional vertical profile extraction, and optional CSV value loading.
    """
    validated = validate_field_param_toml_data(config_data)

    field_section = validated.get("field")
    if not isinstance(field_section, Mapping):
        raise KeyError(
            f"{section_label} requires section [{section_label}.field]"
        )

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
    if kind_key in ("homogeneous", "heterogeneous"):
        specific_section = validated.get(f"field_{kind_key}")
        if isinstance(specific_section, Mapping):
            merged.update(dict(specific_section))

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
            csv_path = _resolve_relative_to(csv_file, base_dir=base_dir)
            csv_key_column = str(merged.get("csv_key_column", "zone_key"))
            csv_value_column = str(merged.get("csv_value_column", "value"))
            merged["values"] = _load_values_mapping_csv(
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
    if "unit" not in payload and "units" in payload:
        payload["unit"] = payload["units"]
    if "values" not in payload and "values_by_key" in payload:
        payload["values"] = payload["values_by_key"]
    if "vertical_profile" not in payload and "field_vertical_profile" in payload:
        payload["vertical_profile"] = payload["field_vertical_profile"]

    # Drop alias keys after normalization so strict schema validation
    # (`extra="forbid"`) does not reject legacy/alternate names.
    payload.pop("identifier", None)
    payload.pop("mode", None)
    payload.pop("units", None)
    payload.pop("values_by_key", None)
    payload.pop("field_vertical_profile", None)

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
