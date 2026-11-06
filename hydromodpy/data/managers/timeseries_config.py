"""Shared Pydantic bases for the configs of point and station time-series variables.

The mixins hold the CSV column names, the station selection and the cache options that
every chronicle variable declares. ``Sim2GridSourceConfig`` and ``LakeChronicleSourceConfig``
add the ``source`` field and its check for the variables that differ only by name.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.field_metadata import field_metadata
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import StationName


class TimeseriesColumnsMixin(HydroModelBase):
    """Shared CSV column-name grammar for point/station time series.

    The defaults follow the SANDRE-style CSV convention used across every
    existing timeseries variable in HydroModPy.
    """

    col_id: Annotated[str, Profile.DEV] = Field(
        default="id",
        description="Column name for the station identifier in location files.",
    )
    col_x: Annotated[str, Profile.DEV] = Field(
        default="x",
        description="Column name for the X coordinate in location files.",
    )
    col_y: Annotated[str, Profile.DEV] = Field(
        default="y",
        description="Column name for the Y coordinate in location files.",
    )
    col_crs: Annotated[str, Profile.DEV] = Field(
        default="crs",
        description="Column name for the CRS in location files.",
    )
    col_datetime: Annotated[str, Profile.USER] = Field(
        default="datetime",
        description="Name of the column that holds the dates in your chronicle CSV files.",
    )
    col_value: Annotated[str, Profile.USER] = Field(
        default="value",
        description="Name of the column that holds the values in your chronicle CSV files.",
    )
    default_crs: Annotated[str, Profile.DEV] = Field(
        default="EPSG:4326",
        description="Default CRS used when a location file omits the CRS column.",
    )


class TimeseriesSelectionMixin(HydroModelBase):
    """Shared station selection, mask, and cache grammar for timeseries variables."""

    station_ids: Annotated[list[StationName] | None, Profile.USER] = Field(
        default=None,
        description=(
            "Station identifiers to select, whether stations are read from a custom "
            "source or fetched from an API source such as Hub'Eau. For a station "
            "source of hydrometry, recharge or runoff, unset means [site] gauge, and "
            "a list that leaves the gauge out is refused."
        ),
        json_schema_extra=field_metadata(site_scoped=True),
    )
    extent: Annotated[
        Literal["watershed", "study_area"] | None,
        Profile.DEV,
    ] = Field(
        default=None,
        description=(
            "Retrieve on the project extent rather than on this source's own filters. Only whether it is SET matters to the loaders; the two literals are not told apart, and a standard project run clips on the delineated watershed either way, through the mask the loader fills in. Declared at DEV level for that reason: a project run neither needs it nor changes with it."
        ),
    )
    force_refresh: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Download this source again instead of reading the cache.",
    )
    mask_path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional SHP/GPKG/GeoJSON/TIF mask to spatially filter stations "
            "or clip gridded sources."
        ),
        json_schema_extra=field_metadata(site_scoped=True),
    )
    source_unit: Annotated[str | None, Profile.USER] = Field(
        default=None,
        description=(
            "Optional source unit for custom gridded .nc/.tif inputs. "
            "When omitted for NetCDF, units are inferred from variable metadata."
        ),
    )


class SparseStationFallbackMixin(HydroModelBase):
    """Shared fallback search behavior for sparse-station timeseries variables."""

    fallback_search_radius_km: Annotated[float | None, Profile.DEV] = Field(
        default=None,
        gt=0.0,
        description=(
            "Maximum search radius (km) used to find a fallback station when "
            "no observation is available inside the requested bbox."
        ),
    )


class Sim2GridSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Source of a variable read from custom files or from SIM2 EDR products.

    A subclass declares ``path``, because the ``InputFile`` role of that field
    is the name of the variable.
    """

    source: Annotated[Literal["custom", "sim2"], Profile.USER] = Field(
        ...,
        description="Data provider: 'custom' for user CSV files, 'sim2' for SIM2 EDR API.",
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> Self:
        if self.source == "custom" and self.path is None:
            raise ValueError(
                "Custom source requires 'path' (directory with location + chronicles, or a .nc/.tif file)."
            )
        return self


class LakeChronicleSourceConfig(TimeseriesColumnsMixin, TimeseriesSelectionMixin):
    """Source of a lake chronicle read from user files, one station per ``lake_id``.

    A subclass declares ``path``, because the ``InputFile`` role of that field
    is the name of the variable.
    """

    source: Annotated[Literal["custom"], Profile.USER] = Field(
        ..., description="Data provider: 'custom' for user files."
    )

    @model_validator(mode="after")
    def _check_source_requirements(self) -> Self:
        if self.source == "custom" and self.path is None:
            raise ValueError(
                "Custom source requires 'path' (directory with location + chronicles)."
            )
        return self


__all__ = [
    "LakeChronicleSourceConfig",
    "Sim2GridSourceConfig",
    "SparseStationFallbackMixin",
    "TimeseriesColumnsMixin",
    "TimeseriesSelectionMixin",
]
