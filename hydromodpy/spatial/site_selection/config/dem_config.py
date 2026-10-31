"""The DEM and hydrology tables of ``[site_selection]``."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, ClassVar, Literal

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile

__all__ = [
    "DemAreaLightConfig",
    "SiteSelectionDemConfig",
    "HydrologyConfig",
]


class SiteSelectionDemConfig(HydroModelBase):
    """DEM source requested by site selection."""

    model_refused_keys: ClassVar[Mapping[str, str]] = {
        "resolution_m": (
            "no step resampled the DEM to it. The DEM keeps the resolution of its "
            "source: set resolution_m under [data.dem], or give dem.path a raster at "
            "the resolution you want."
        ),
        "cache_policy": (
            "no step read it. Write dem.force_refresh = true to fetch the DEM again "
            "instead of reading the cache."
        ),
    }

    source: Annotated[Literal["custom", "data", "ign_geoplateforme_dem"], Profile.USER] = Field(
        default="custom",
        description=(
            "Where the selection takes its DEM when dem.path is empty and the file holds "
            "no [data.dem] section. A dem.path or a [data.dem] section always wins."
        ),
        json_schema_extra={
            "value_docs": {
                "custom": "Takes no DEM of its own: dem.path or [data.dem] must give one.",
                "data": "Takes no DEM of its own: the [data.dem] section of the file gives it.",
                "ign_geoplateforme_dem": (
                    "Requests the IGN Geoplateforme DEM over the territory when neither "
                    "dem.path nor [data.dem] gives one."
                ),
            }
        },
    )
    path: Annotated[Path | None, Profile.USER] = Field(
        default=None,
        description=(
            "Local DEM raster used to delineate the catchments. When set, it wins over "
            "[data.dem] and over source."
        ),
    )
    margin_km: Annotated[float, Profile.USER] = Field(
        default=0.0,
        ge=0,
        description="DEM request margin around the territory in kilometres.",
    )
    request_extent: Annotated[Literal["territory", "outlets"], Profile.USER] = Field(
        default="territory",
        description=(
            "Area the DEM is requested over through [data.dem]. "
            "'territory' requests the configured selection territory; 'outlets' "
            "requests the bounding box of imported outlets expanded by margin_km."
        ),
    )
    map_background_extent: Annotated[
        Literal["none", "delineation", "territory"],
        Profile.USER,
    ] = Field(
        default="delineation",
        description=(
            "DEM extent used only for review-map background. 'delineation' reuses "
            "the DEM used to calculate basin contours; 'territory' loads a "
            "regional DEM through [data.dem] without using it for delineation."
        ),
        json_schema_extra={
            "value_docs": {
                "none": "Skips loading any DEM background for the review map.",
                "delineation": (
                    "Reuses the DEM already used to delineate basin contours as background."
                ),
                "territory": (
                    "Loads a separate regional DEM over the full territory for the background."
                ),
            }
        },
    )
    force_refresh: Annotated[bool, Profile.USER] = Field(
        default=False,
        description="Ignore existing cached data when supported by the provider.",
    )


class HydrologyConfig(HydroModelBase):
    """DEM-derived hydrologic products requested by the selection workflow."""

    method: Annotated[Literal["dem_only"], Profile.USER] = Field(
        default="dem_only",
        description=(
            "How the flow products (directions, accumulation, streams) are made. "
            "'dem_only' derives them from the DEM alone and is the only value today."
        ),
    )
    flow_algorithm: Annotated[Literal["d8"], Profile.USER] = Field(
        default="d8",
        description="Flow routing algorithm used by existing spatial products.",
    )
    hydrologic_conditioning: Annotated[
        Literal["existing_default", "fill", "breach"],
        Profile.USER,
    ] = Field(
        default="existing_default",
        description="DEM conditioning strategy forwarded to existing flow products.",
        json_schema_extra={
            "value_docs": {
                "existing_default": (
                    "Forwards 'fill' to the flow products; it is the site-selection default."
                ),
                "fill": "Raises each depression to its spill elevation before routing flow.",
                "breach": (
                    "Carves a channel through each depression, preserving natural flow paths."
                ),
            }
        },
    )
    network_threshold_area_km2: Annotated[float, Profile.USER] = Field(
        default=1.0,
        gt=0,
        description="Contributing-area threshold used to extract the stream network.",
    )
    compute_strahler: Annotated[bool, Profile.USER] = Field(
        default=True,
        description="Request Strahler diagnostics if existing spatial primitives support them.",
    )

    @property
    def dem_correction_type(self) -> Literal["fill", "breach"]:
        """Return the existing flow-products correction keyword."""

        if self.hydrologic_conditioning == "breach":
            return "breach"
        return "fill"


class DemAreaLightConfig(HydroModelBase):
    """Minimal DEM-only basin selection settings."""

    target_area_km2: Annotated[float, Profile.USER] = Field(
        default=100.0,
        gt=0,
        description="Preferred upstream basin area for DEM-only candidate outlets.",
    )
    min_area_km2: Annotated[float, Profile.USER] = Field(
        default=75.0,
        gt=0,
        description="Smallest upstream area, in km2, a DEM-only candidate basin may have.",
    )
    max_area_km2: Annotated[float, Profile.USER] = Field(
        default=125.0,
        gt=0,
        description="Largest upstream area, in km2, a DEM-only candidate basin may have.",
    )
    n_basins: Annotated[int, Profile.USER] = Field(
        default=50,
        gt=0,
        description=(
            "Number of basins the DEM-only selection keeps. It replaces "
            "spatial_selection.max_selected_sites in that selection. A count."
        ),
        json_schema_extra={"unit": "-"},
    )
    max_candidates_before_delineation: Annotated[int | None, Profile.USER] = Field(
        default=None,
        gt=0,
        description=(
            "Most candidate outlets delineated before the final selection. A lower value "
            "runs faster but can leave fewer accepted basins after spatial filtering. "
            "Unset, it is 20 times n_basins. A count."
        ),
        json_schema_extra={"unit": "-"},
    )

    @model_validator(mode="after")
    def _validate_area_window(self) -> DemAreaLightConfig:
        if self.min_area_km2 > self.max_area_km2:
            raise ValueError("min_area_km2 must be <= max_area_km2.")
        if not (self.min_area_km2 <= self.target_area_km2 <= self.max_area_km2):
            raise ValueError("target_area_km2 must be inside [min_area_km2, max_area_km2].")
        return self
