"""Pydantic schema and runtime state for the data-overview pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.profile import Profile
from hydromodpy.core.state.data import LoadedDataContext
from hydromodpy.core.config.base import HydroModelBase

if TYPE_CHECKING:
    from hydromodpy.core.config import HydroModPyConfig
    from hydromodpy.core.workspace.workspace import Workspace
    from hydromodpy.spatial.geographic.core.derived_features import (
        GeographicDerivedFeatures,
    )
    from hydromodpy.spatial.geographic.core.domain_geographic_pipeline import (
        DomainGeographicContext,
    )
    from hydromodpy.spatial.geographic.catchment_delineation import CatchmentDelineation


class OverviewPanelsConfig(HydroModelBase):
    """Toggle individual report panels on/off."""

    model_config = ConfigDict(extra="forbid")

    map_dem: Annotated[bool, Profile.USER] = Field(True, description="DEM elevation map.")
    map_geology: Annotated[bool, Profile.USER] = Field(True, description="Geology lithology map.")
    map_hydrography: Annotated[bool, Profile.USER] = Field(True, description="River network map.")
    stats_card: Annotated[bool, Profile.USER] = Field(True, description="Watershed metrics card.")
    timeseries_discharge: Annotated[bool, Profile.USER] = Field(True, description="Observed discharge.")
    timeseries_piezometry: Annotated[bool, Profile.USER] = Field(True, description="Observed piezometry.")
    climatic_summary: Annotated[bool, Profile.USER] = Field(True, description="P/ETP monthly bars.")
    timeseries_intermittency: Annotated[bool, Profile.USER] = Field(True, description="ONDE intermittency.")
    timeseries_water_quality: Annotated[bool, Profile.USER] = Field(True, description="Water-quality series.")
    station_inventory: Annotated[bool, Profile.USER] = Field(True, description="Station inventory table.")


class OverviewSection(HydroModelBase):
    """Overview report settings (watershed identity card)."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, Profile.USER] = Field("", description="Watershed name.")
    date_start: Annotated[str | None, Profile.USER] = Field(None, description="Global start date (YYYY-MM-DD).")
    date_end: Annotated[str | None, Profile.USER] = Field(None, description="Global end date (YYYY-MM-DD).")
    panels: Annotated[OverviewPanelsConfig, Profile.USER] = Field(
        default_factory=OverviewPanelsConfig,
        description="Panel toggles.",
    )


@dataclass
class DataOverviewState:
    """Runtime state threaded through the overview pipeline phases."""

    cfg: "HydroModPyConfig"
    workspace: "Workspace | None" = None
    geographic: "CatchmentDelineation | None" = None
    geographic_features: "GeographicDerivedFeatures | None" = None
    domain_geographic: "DomainGeographicContext | None" = None
    loaded_data: LoadedDataContext = field(default_factory=LoadedDataContext)
