"""Pydantic configuration for hydrometry data sources."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import ConfigDict, Field, model_validator

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.tracking import InputFile
from hydromodpy.data.base_config import BaseVariableConfig


class HydrometrySourceConfig(HydroModelBase):
    """Configuration for ONE hydrometry data source."""

    model_config = ConfigDict(extra="forbid")

    source: Annotated[Literal["custom", "hubeau"], Profile.USER] = Field(
        ..., description="Data provider: 'custom' for user files, 'hubeau' for Hub'Eau API."
    )

    # --- Custom source fields ---
    path: Annotated[
        Path | None,
        Profile.USER,
        InputFile(role="hydrometry", category="data"),
    ] = Field(default=None, description="Directory containing location file and chronicle CSVs.")
    col_id: Annotated[str, Profile.DEV] = Field(
        default="id", description="Column name for station identifier in location file."
    )
    col_x: Annotated[str, Profile.DEV] = Field(
        default="x", description="Column name for X coordinate in location CSV."
    )
    col_y: Annotated[str, Profile.DEV] = Field(
        default="y", description="Column name for Y coordinate in location CSV."
    )
    col_crs: Annotated[str, Profile.DEV] = Field(
        default="crs", description="Column name for CRS in location CSV."
    )
    default_crs: Annotated[str, Profile.DEV] = Field(
        default="EPSG:4326", description="Default CRS when not specified in location file."
    )
    col_datetime: Annotated[str, Profile.DEV] = Field(
        default="datetime", description="Column name for datetime in chronicle CSVs."
    )
    col_value: Annotated[str, Profile.DEV] = Field(
        default="value", description="Column name for value in chronicle CSVs."
    )

    # --- Spatial mask ---
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None, description="SHP/GPKG/GeoJSON/TIF mask to spatially filter stations."
    )

    # --- API source fields ---
    product: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Hub'Eau variable code (e.g. 'QmnJ', 'QmM', 'HmnJ').",
    )
    require_observations: Annotated[bool, Profile.DEV] = Field(
        default=True, description="Only keep stations that have observations in the period."
    )
    fallback_search_radius_km: Annotated[float | None, Profile.DEV] = Field(
        default=None, description="If no station found in bbox, expand search by this radius (km)."
    )

    # --- Common fields ---
    station_ids: Annotated[list[str] | None, Profile.USER] = Field(
        default=None, description="Explicit list of station ids to load."
    )
    extent: Annotated[Literal["watershed", "study_area"] | None, Profile.USER] = Field(
        default=None,
        description="Enable bbox-based station discovery using the project extent.",
    )
    force_refresh: Annotated[bool, Profile.DEV] = Field(
        default=False,
        description="Ignore cache and re-download from API.",
    )
    source_unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description="Source unit of custom data (e.g. 'L/s'). If None, inferred from LOC file or assumed same as internal unit.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> HydrometrySourceConfig:
        if self.source == "custom":
            if self.path is None:
                raise ValueError(
                    "Custom source requires 'path' (directory with location + chronicles)."
                )
        if self.source == "hubeau":
            if self.product is None:
                raise ValueError("Hub'Eau source requires 'product' (e.g. 'QmnJ').")
        return self


class HydrometryConfig(BaseVariableConfig):
    """Top-level hydrometry configuration (list of sources)."""

    _TOML_SECTION = "hydrometry"

    sources: Annotated[list[HydrometrySourceConfig], Profile.USER] = Field(
        ..., min_length=1, description="At least one data source."
    )

    @classmethod
    def hubeau(
        cls,
        *,
        stations: list[str] | None = None,
        product: str = "QmnJ",
        start: str | None = None,
        end: str | None = None,
        extent: Literal["watershed", "study_area"] | None = None,
        **overrides,
    ) -> HydrometryConfig:
        """HydrometryConfig reading discharge timeseries from the Hub'Eau API."""
        source_kwargs: dict[str, object] = {"product": product}
        if stations is not None:
            source_kwargs["station_ids"] = list(stations)
        if extent is not None:
            source_kwargs["extent"] = extent
        source_kwargs.update(overrides)
        return cls(
            date_start=start,
            date_end=end,
            sources=[HydrometrySourceConfig(source="hubeau", **source_kwargs)],
        )

    @classmethod
    def from_csv_directory(
        cls,
        path: str | Path,
        *,
        start: str | None = None,
        end: str | None = None,
        col_id: str = "id",
        col_x: str = "x",
        col_y: str = "y",
        col_datetime: str = "datetime",
        col_value: str = "value",
        **overrides,
    ) -> HydrometryConfig:
        """HydrometryConfig reading a directory of station CSVs."""
        return cls(
            date_start=start,
            date_end=end,
            sources=[
                HydrometrySourceConfig(
                    source="custom",
                    path=Path(path),
                    col_id=col_id,
                    col_x=col_x,
                    col_y=col_y,
                    col_datetime=col_datetime,
                    col_value=col_value,
                    **overrides,
                )
            ],
        )
