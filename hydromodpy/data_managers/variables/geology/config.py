"""Pydantic configuration for geology data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
