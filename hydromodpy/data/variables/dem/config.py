"""Pydantic configuration for DEM data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from hydromodpy.core.config.param_level import ParamLevel


class DemSourceConfig(BaseModel):
    """Configuration for ONE DEM data source.

    Supported sources:

    - ``custom``: user-provided raster file (GeoTIFF, Esri ASCII Grid, NetCDF).
    - ``ign_bdalti``: IGN BD ALTI® 25 m — French national MNT downloaded
      per-department from the GéoPlateforme.
    """

    model_config = ConfigDict(extra="forbid")

    source: Annotated[
        Literal["custom", "ign_bdalti"], ParamLevel("user")
    ] = Field(
        ...,
        description=(
            "Data provider: 'custom' for user files (TIF/ASC/NC), "
            "'ign_bdalti' for the IGN BD ALTI 25 m MNT."
        ),
    )

    # --- Custom source fields ---
    path: Annotated[Optional[Path], ParamLevel("user")] = Field(
        default=None,
        description="Path to custom DEM file or directory (TIF, ASC, NC).",
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
    def _check_source_requirements(self) -> "DemSourceConfig":
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (TIF, ASC, or NC file)."
                )
        return self


class DemConfig(BaseModel):
    """Top-level DEM variable configuration.

    Example TOML::

        [data.dem]

        [[data.dem.sources]]
        source = "ign_bdalti"

        [[data.dem.sources]]
        source = "custom"
        path = "data/my_dem.tif"
    """

    model_config = ConfigDict(extra="forbid")

    sources: Annotated[list[DemSourceConfig], ParamLevel("user")] = Field(
        ...,
        min_length=1,
        description="At least one DEM data source.",
    )
