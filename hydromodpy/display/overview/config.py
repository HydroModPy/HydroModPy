"""Pydantic configuration for the data-overview report (display layer)."""

from __future__ import annotations

from typing import Annotated

from pydantic import ConfigDict, Field

from hydromodpy.core.config.base import HydroModelBase
from hydromodpy.core.config.profile import Profile
from hydromodpy.core.state.data import LoadedDataContext

if TYPE_CHECKING:
    from hydromodpy.config import HydroModPyConfig
    from hydromodpy.core.workspace.workspace import Workspace
    from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation
    from hydromodpy.spatial.geographic.core.derived_features import (
        GeographicDerivedFeatures,
    )
    from hydromodpy.spatial.geographic.core.domain_geographic_pipeline import (
        DomainGeographicContext,
    )


class OverviewPanelsConfig(HydroModelBase):
    """Toggle individual report panels on/off."""

    model_config = ConfigDict(extra="forbid")

    map_dem: Annotated[bool, Profile.USER] = Field(True, description="DEM elevation map.")
    map_geology: Annotated[bool, Profile.USER] = Field(True, description="Geology lithology map.")
    map_hydrography: Annotated[bool, Profile.USER] = Field(True, description="River network map.")
    stats_card: Annotated[bool, Profile.USER] = Field(True, description="Watershed metrics card.")
    timeseries_discharge: Annotated[bool, Profile.USER] = Field(
        True, description="Observed discharge."
    )
    timeseries_piezometry: Annotated[bool, Profile.USER] = Field(
        True, description="Observed piezometry."
    )
    climatic_summary: Annotated[bool, Profile.USER] = Field(True, description="P/ETP monthly bars.")
    timeseries_intermittency: Annotated[bool, Profile.USER] = Field(
        True, description="ONDE intermittency."
    )
    timeseries_water_quality: Annotated[bool, Profile.USER] = Field(
        True, description="Water-quality series."
    )
    station_inventory: Annotated[bool, Profile.USER] = Field(
        True, description="Station inventory table."
    )


class OverviewSection(HydroModelBase):
    """Overview report settings (watershed identity card)."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Profile.USER] = Field("", description="Watershed name.")
    date_start: Annotated[str | None, Profile.USER] = Field(
        None, description="Global start date (YYYY-MM-DD)."
    )
    date_end: Annotated[str | None, Profile.USER] = Field(
        None, description="Global end date (YYYY-MM-DD)."
    )
    panels: Annotated[OverviewPanelsConfig, Profile.USER] = Field(
        default_factory=OverviewPanelsConfig,
        description="Panel toggles.",
    )
