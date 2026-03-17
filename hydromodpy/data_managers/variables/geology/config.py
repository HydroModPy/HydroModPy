"""Pydantic configuration for geology data sources."""

from __future__ import annotations

from pathlib import Path
import tomllib
from typing import Annotated, Any, Literal, Mapping, Optional

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from hydromodpy.config.param_level import ParamLevel


class GeologySourceConfig(BaseModel):
    """Configuration for ONE geology data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[
        Literal["custom", "brgm_1m", "brgm_50k"], ParamLevel("user")
    ] = Field(
        ...,
        description=(
            "Data provider: 'custom' for user files (SHP/GPKG/TIF/CSV), "
            "'brgm_1m' for the 1:1M national geological map, "
            "'brgm_50k' for the 1:50K departmental geological maps."
        ),
    )

    # --- Custom source fields ---
    path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None,
        description="Path to custom geology file or directory (SHP, GPKG, TIF, CSV).",
    )
    code_field: Annotated[Optional[str], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Attribute column for geology codes in custom vector files "
            "(SHP/GPKG). Required for custom vector sources. "
            "Ignored for BRGM sources (always CODE_LEG)."
        ),
    )
    values_table_path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None,
        description=(
            "Optional CSV linking geology codes to descriptions. "
            "Columns: geology_code, description."
        ),
    )

    # --- CSV interpolation fields ---
    col_x: Annotated[str, ParamLevel("dev")] = Field(
        default="x", description="Column for X coordinate in CSV.",
    )
    col_y: Annotated[str, ParamLevel("dev")] = Field(
        default="y", description="Column for Y coordinate in CSV.",
    )
    col_code: Annotated[str, ParamLevel("dev")] = Field(
        default="geology_code", description="Column for geology code in CSV.",
    )
    default_crs: Annotated[str, ParamLevel("dev")] = Field(
        default="EPSG:2154", description="Default CRS for CSV points.",
    )

    # --- Spatial mask ---
    mask_path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None,
        description="SHP/GPKG/GeoJSON mask for spatial filtering/clipping.",
    )
    extent: Annotated[Optional[Literal["watershed", "study_area"]], ParamLevel("user")] = Field(
        default=None,
        description="Use project extent for bbox-based data retrieval.",
    )

    # --- Common ---
    force_refresh: Annotated[bool, ParamLevel("dev")] = Field(
        default=False,
        description="Ignore cache and re-download from API.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> "GeologySourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (SHP, GPKG, TIF, or CSV file/directory)."
                )
            # code_field is required for custom vector sources.
            # For raster/CSV the code_field is unused (raster has numeric bands,
            # CSV uses col_code).  We validate at load time when we know the
            # file extension.
        if self.source in ("brgm_1m", "brgm_50k") and self.code_field is not None:
            raise ValueError(
                f"'code_field' must not be set for '{self.source}' sources — "
                "BRGM data always uses 'CODE_LEG'."
            )
        return self


class GeologyConfig(BaseModel):
    """Top-level geology variable configuration.

    Example TOML::

        [data.geology]
        cell_samples_per_axis = 8

        [[data.geology.sources]]
        source = "brgm_1m"

        [[data.geology.sources]]
        source = "custom"
        path = "data/my_geology.gpkg"
        code_field = "LITHOLOGY"
    """

    model_config = ConfigDict(extra="forbid")

    sources: Annotated[list[GeologySourceConfig], ParamLevel("user")] = Field(
        default_factory=lambda: [GeologySourceConfig(source="brgm_1m")],
        min_length=1,
        description="At least one geology data source. Defaults to BRGM 1:1M.",
    )

    id: Annotated[str, ParamLevel("user")] = Field(
        default="field_geology",
        description="Identifier of the geology spatial field.",
    )
    cell_samples_per_axis: Annotated[int, ParamLevel("dev")] = Field(
        default=8,
        ge=2,
        description=(
            "Sub-sampling density for GeologyField.on_mesh(). "
            "Higher = more precise geology interface, slower runtime."
        ),
    )

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        text = str(value).strip()
        if not text:
            raise ValueError("geology.id cannot be empty")
        return text


# ---------------------------------------------------------------------------
# Standalone geology field schemas (used by GeologyField.from_dict/from_toml
# and runtime_loader for direct field construction).
# ---------------------------------------------------------------------------

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
    """Schema for geology data source definition (standalone field construction)."""

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
    """Optional sea-mask override for coastal workflows."""

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
    """Top-level schema for one geology field definition (standalone construction)."""

    model_config = ConfigDict(extra="forbid")

    id: str = "field_geology"
    source: GeologySourceSchema
    clip_polygon_path: str | None = None
    landsea: GeologyLandSeaSchema = Field(default_factory=GeologyLandSeaSchema)
    cell_samples_per_axis: int = 8

    @field_validator("id")
    @classmethod
    def _validate_id_standalone(cls, value):
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
    """Validate raw geology config mapping and return normalized Python data."""
    if not isinstance(config_data, Mapping):
        raise ValueError("geology configuration must be a mapping")
    try:
        parsed = GeologyConfigSchema.model_validate(dict(config_data))
    except ValidationError as exc:
        raise ValueError(str(exc)) from exc
    return parsed.model_dump(mode="python")


def load_geology_toml(config_path: str | Path, section: str = "geology") -> dict[str, Any]:
    """Load TOML file and validate one geology section."""
    path = Path(config_path)
    payload = tomllib.loads(path.read_text(encoding="utf-8-sig"))
    section_cfg = _get_nested_section(payload, section)
    try:
        return validate_geology_config_data(section_cfg)
    except ValueError as exc:
        raise ValueError(f"Invalid geology configuration in {path}: {exc}") from exc
