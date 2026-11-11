"""Pydantic configuration for lake geometry data sources."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import Field

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.tracking.input_file import InputFile
from hydromodpy.data.source.url import UrlSourceOptions


class FileLakeGeometrySource(HydroModelBase):
    """User-provided lake geometry file (SHP/GPKG/GeoJSON).

    The vector file holds the lake/reservoir footprint polygon(s) - and, where
    relevant, the dam line and outlet points - that the LAK builder intersects
    with the DISV mesh to resolve the lake cells.
    """

    source: Annotated[Literal["file"], Profile.USER] = Field(
        default="file",
        description="Discriminator tag selecting the 'file' lake-geometry provider.",
    )
    path: Annotated[
        Path,
        Profile.USER,
        InputFile(role="lake_geometry", category="data"),
    ] = Field(
        ...,
        description="Path to a user lake-geometry vector file (SHP, GPKG, GeoJSON).",
        json_schema_extra=field_metadata(site_scoped=True),
    )
    default_crs: Annotated[str, Profile.USER] = Field(
        default="EPSG:2154",
        description=(
            "CRS to use for a file that carries none of its own. Only a value written "
            "here is used: without it, a file with no CRS is refused."
        ),
    )


class UrlLakeGeometrySource(UrlSourceOptions, HydroModelBase):
    """Remote lake geometry file, downloaded into the data cache by the ``url`` source."""

    source: Annotated[Literal["url"], Profile.USER] = Field(
        default="url",
        description="Discriminator tag selecting the 'url' lake-geometry provider.",
    )


class LakeGeometryConfig(HydroModelBase):
    """Top-level lake-geometry variable configuration.

    Example TOML::

        [[data.lake_geometry.sources]]
        source = "file"
        path = "data/lake_geometry/lake_geometry_file_lac0.gpkg"
    """

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "id": (
            "no step read the name of the lake-geometry field. Each lake is named by the "
            "lake_id of its table under flow.sinks_sources.lakes."
        ),
    }

    sources: Annotated[list[FileLakeGeometrySource | UrlLakeGeometrySource], Profile.USER] = Field(
        ...,
        min_length=1,
        description="At least one lake-geometry data source.",
    )

    @classmethod
    def from_vector(cls, path: str | Path, **overrides) -> LakeGeometryConfig:
        """LakeGeometryConfig from a user polygon vector file (SHP/GPKG/GeoJSON)."""
        return cls(sources=[FileLakeGeometrySource(path=Path(path))], **overrides)
