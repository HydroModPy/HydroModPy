"""Pydantic configuration and runtime state for the data-overview pipeline.

``OverviewSection`` and ``OverviewPanelsConfig`` define the ``[overview]``
TOML section, integrated as an optional field of
:class:`~hydromodpy.core.config.HydroModPyConfig`.

``DataOverviewState`` is the runtime state container threaded through the
overview pipeline phases.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any, TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from hydromodpy.core.config.param_level import ParamLevel
from hydromodpy.core.state.data import LoadedDataContext

if TYPE_CHECKING:
    from hydromodpy.core.config import HydroModPyConfig
    from hydromodpy.spatial.geographic.core.derived_features import GeographicDerivedFeatures
    from hydromodpy.spatial.geographic.core.domain_geographic_pipeline import (
        DomainGeographicContext,
    )
    from hydromodpy.spatial.geographic.geographic import Geographic
    from hydromodpy.core.workspace.workspace import Workspace


class OverviewPanelsConfig(BaseModel):
    """Toggle individual report panels on/off."""

    model_config = ConfigDict(extra="forbid")

    map_dem: Annotated[bool, ParamLevel("user")] = Field(True, description="DEM elevation map with stations overlay.")
    map_geology: Annotated[bool, ParamLevel("user")] = Field(True, description="Geology lithology map.")
    map_hydrography: Annotated[bool, ParamLevel("user")] = Field(True, description="River network map with Strahler orders.")
    stats_card: Annotated[bool, ParamLevel("user")] = Field(True, description="Key watershed metrics card.")
    timeseries_discharge: Annotated[bool, ParamLevel("user")] = Field(True, description="Observed discharge time series.")
    timeseries_piezometry: Annotated[bool, ParamLevel("user")] = Field(True, description="Observed piezometric levels time series.")
    climatic_summary: Annotated[bool, ParamLevel("user")] = Field(True, description="Mean monthly precipitation and ETP bars.")
    timeseries_intermittency: Annotated[bool, ParamLevel("user")] = Field(True, description="ONDE flow-state observations timeline.")
    timeseries_water_quality: Annotated[bool, ParamLevel("user")] = Field(True, description="Water quality parameters time series.")
    station_inventory: Annotated[bool, ParamLevel("user")] = Field(True, description="Table listing all stations (type, id, coordinates, period).")


class OverviewSection(BaseModel):
    """Overview report settings (watershed identity card)."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, ParamLevel("user")] = Field("", description="Watershed name displayed on report panels. Defaults to workspace catch_name.")
    date_start: Annotated[str | None, ParamLevel("user")] = Field(None, description="Global start date (YYYY-MM-DD). Injected into data sections without explicit dates.")
    date_end: Annotated[str | None, ParamLevel("user")] = Field(None, description="Global end date (YYYY-MM-DD). Injected into data sections without explicit dates.")
    panels: Annotated[OverviewPanelsConfig, ParamLevel("user")] = Field(default_factory=OverviewPanelsConfig, description="Toggle individual report panels.")


@dataclass
class DataOverviewState:
    """Carries all runtime objects through the overview pipeline."""

    cfg: HydroModPyConfig
    workspace: Workspace | None = None
    geographic: Geographic | None = None
    geographic_features: GeographicDerivedFeatures | None = None
    domain_geographic: DomainGeographicContext | None = None
    loaded_data: LoadedDataContext = field(default_factory=LoadedDataContext)
