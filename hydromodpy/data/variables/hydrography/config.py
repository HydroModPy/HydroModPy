"""Pydantic configuration for hydrography data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.core.config.param_level import ParamLevel


class HydrographySourceConfig(BaseModel):
    """Configuration for ONE hydrography data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[
        Literal["custom", "osm", "bdtopage", "euhydro"], ParamLevel("user")
    ] = Field(..., description="Data provider.")

    # --- Custom source fields ---
    path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None,
        description="Path to a vector file (SHP/GPKG/GeoJSON), raster (TIF/TIFF), or directory containing one.",
    )
    rasterize_field: Annotated[str, ParamLevel("user")] = Field(
        default="FID",
        description="Attribute field used when rasterising the vector layer.",
    )

    # --- BD Topage (Sandre WFS) ---
    typename: Annotated[str, ParamLevel("dev")] = Field(
        default="sa:CoursEau_FXX_Topage2025",
        description="WFS typename for BD Topage.",
    )
    page_size: Annotated[int, ParamLevel("dev")] = Field(
        default=2000,
        description="WFS pagination page size (BD Topage).",
    )

    # --- EU-Hydro (EEA REST) ---
    group_name: Annotated[str, ParamLevel("dev")] = Field(
        default="River_Net_lines",
        description="MapServer group name for EU-Hydro layer discovery.",
    )
    euhydro_page_size: Annotated[int, ParamLevel("dev")] = Field(
        default=1000,
        description="Pagination page size for EU-Hydro REST queries.",
    )

    # --- Cache ---
    force_refresh: Annotated[bool, ParamLevel("dev")] = Field(
        default=False,
        description="Bypass API cache and re-download data.",
    )

    # --- OSM ---
    waterway_types: Annotated[list[str], ParamLevel("dev")] = Field(
        default_factory=lambda: ["river", "stream"],
        description="OSM waterway tag values to fetch.",
    )

    @model_validator(mode="after")
    def _check_custom_requires_path(self) -> "HydrographySourceConfig":
        if self.source == "custom" and self.path is None:
            raise ValueError("Custom source requires 'path'.")
        return self


class HydrographyConfig(BaseModel):
    """Top-level hydrography configuration (list of sources)."""

    model_config = ConfigDict(extra="forbid")

    sources: Annotated[list[HydrographySourceConfig], ParamLevel("user")] = Field(
        ..., min_length=1, description="At least one hydrography data source.",
    )
