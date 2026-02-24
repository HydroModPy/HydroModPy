"""
Pydantic schemas and helpers for geology field case configuration.

The goal is to validate geology-specific settings before creating a
`GeologyField` instance. This keeps I/O and spatial processing code focused on
their domain logic.

Didactic overview
-----------------
The geology case configuration is intentionally split into clear blocks:

1) `[geology]`
   - global field identity and processing options.
2) `[geology.source]`
   - where geology comes from (raster or vector).
3) `[geology.landsea]` (optional)
   - optional override on sea pixels.

This separation makes the intent explicit:
- `source` defines *what geology is*,
- `landsea` defines *how some pixels are corrected*,
- `geology` defines *how to expose the final field*.
"""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Any, Mapping

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


SUPPORTED_SOURCE_KINDS = ("auto", "raster", "vector")


def _get_nested_section(payload: Mapping[str, Any], dotted_path: str) -> Mapping[str, Any]:
    """Resolve a nested TOML section from a dotted path."""
    current: Any = payload
    for token in str(dotted_path).split("."):
        if not isinstance(current, Mapping) or token not in current:
            raise KeyError(f"Missing TOML section '{dotted_path}'")
        current = current[token]
    if not isinstance(current, Mapping):
        raise ValueError(f"TOML section '{dotted_path}' must be a mapping")
    return current


class GeologySourceSchema(BaseModel):
    """
    Schema for geology data source definition.

    Examples
    --------
    Raster source:
        source = {
            "path": "data/France/dem/regional dem.tif",
            "kind": "raster",
        }

    Vector source:
        source = {
            "path": "data/France/geology/GEO1M.shp",
            "kind": "vector",
            "code_field": "CODE_LEG",
            "reference_raster_path": "data/France/dem/regional dem.tif",
        }
    """

    model_config = ConfigDict(extra="forbid")

    path: str
    kind: str = "auto"
    code_field: str | None = None
    reference_raster_path: str | None = None
    all_touched: bool = False

    @field_validator("path")
    @classmethod
    def _validate_path(cls, value):
        text = str(value).strip()
        if not text:
            raise ValueError("source.path cannot be empty")
        return text

    @field_validator("kind")
    @classmethod
    def _validate_kind(cls, value):
        key = str(value).strip().lower()
        if key not in SUPPORTED_SOURCE_KINDS:
            allowed = ", ".join(SUPPORTED_SOURCE_KINDS)
            raise ValueError(f"Unsupported source.kind '{value}'. Allowed: {allowed}")
        return key

    @field_validator("code_field", "reference_raster_path")
    @classmethod
    def _validate_optional_non_empty(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("value cannot be empty when provided")
        return text

    @model_validator(mode="after")
    def _validate_vector_constraints(self):
        if self.kind == "vector":
            if self.code_field is None:
                raise ValueError("For vector source, 'code_field' is required")
            if self.reference_raster_path is None:
                raise ValueError("For vector source, 'reference_raster_path' is required")
        return self


class GeologyLandSeaSchema(BaseModel):
    """
    Optional sea-mask override for coastal workflows.

    Concept
    -------
    A land/sea raster can be used to force sea cells to one geology code.
    For example, if sea is encoded as `0` in the land/sea raster:
        enabled = true
        sea_value = 0
        override_code = "1"
    then all sea pixels become geology zone `"1"`.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    path: str | None = None
    sea_value: float = 0.0
    override_code: str = "1"

    @field_validator("path")
    @classmethod
    def _validate_optional_path(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("landsea.path cannot be empty when provided")
        return text

    @field_validator("sea_value")
    @classmethod
    def _validate_sea_value(cls, value):
        return float(value)

    @field_validator("override_code")
    @classmethod
    def _validate_override_code(cls, value):
        text = str(value).strip()
        if not text:
            raise ValueError("landsea.override_code cannot be empty")
        return text

    @model_validator(mode="after")
    def _validate_path_when_enabled(self):
        if self.enabled and self.path is None:
            raise ValueError("landsea.path is required when landsea.enabled=true")
        return self


class GeologyConfigSchema(BaseModel):
    """
    Top-level schema for one geology field definition.

    Minimal example (raster source):
        {
            "id": "field_geology",
            "source": {"path": "data/France/dem/regional dem.tif", "kind": "raster"},
        }
    """

    model_config = ConfigDict(extra="forbid")

    id: str = "field_geology"
    source: GeologySourceSchema
    clip_polygon_path: str | None = None
    landsea: GeologyLandSeaSchema = Field(default_factory=GeologyLandSeaSchema)
    cell_samples_per_axis: int = 8

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value):
        text = str(value).strip()
        if not text:
            raise ValueError("geology.id cannot be empty")
        return text

    @field_validator("clip_polygon_path")
    @classmethod
    def _validate_optional_clip_path(cls, value):
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            raise ValueError("clip_polygon_path cannot be empty when provided")
        return text

    @field_validator("cell_samples_per_axis")
    @classmethod
    def _validate_cell_samples_per_axis(cls, value):
        out = int(value)
        if out < 2:
            raise ValueError("cell_samples_per_axis must be >= 2")
        return out


def validate_geology_config_data(config_data: Mapping[str, Any]) -> dict[str, Any]:
    """
    Validate raw geology config mapping and return normalized Python data.

    Why validate here?
    ------------------
    This function is the contract boundary:
    - invalid config is rejected early with explicit errors,
    - downstream code can assume a coherent configuration.
    """
    if not isinstance(config_data, Mapping):
        raise ValueError("geology configuration must be a mapping")
    try:
        parsed = GeologyConfigSchema.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python")


def load_geology_toml(config_path: str | Path, section: str = "geology") -> dict[str, Any]:
    """
    Load TOML file and validate one geology section.

    Example
    -------
    payload = load_geology_toml(
        "hydromodpy/field/cases/geology/geology_config.toml",
        section="geology",
    )
    """
    path = Path(config_path)
    # Use utf-8-sig so files with a UTF-8 BOM remain parseable.
    payload = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    section_cfg = _get_nested_section(payload, section)
    try:
        return validate_geology_config_data(section_cfg)
    except ValueError as exc:
        raise ValueError(f"Invalid geology configuration in {path}: {exc}") from exc

