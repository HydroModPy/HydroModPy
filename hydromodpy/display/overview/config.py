"""Pydantic configuration for the data-overview report (display layer)."""

from __future__ import annotations

from typing import Annotated

from pydantic import Field, model_validator

from hydromodpy.core.config_kit.base import HydroModelBase
from hydromodpy.core.config_kit.profile import Profile
from hydromodpy.core.config_kit.types import IsoDateStr


class OverviewPanelsConfig(HydroModelBase):
    """Toggle individual report panels on/off."""

    map_dem: Annotated[bool, Profile.USER] = Field(
        True,
        description="Draw the map of the DEM elevations with the watershed, streams and stations.",
    )
    map_geology: Annotated[bool, Profile.USER] = Field(
        True,
        description="Draw the map of the geology units over the watershed. It needs loaded geology.",
    )
    map_hydrography: Annotated[bool, Profile.USER] = Field(
        True,
        description="Draw the map of the mapped BD Topage stream network over the watershed.",
    )
    stats_card: Annotated[bool, Profile.USER] = Field(
        True,
        description=(
            "Draw the identity card: name, area, period, number of stream reaches and "
            "stations of each kind."
        ),
    )
    timeseries_discharge: Annotated[bool, Profile.USER] = Field(
        True,
        description="Draw the observed discharge series of the hydrometric stations, in m3/s.",
    )
    timeseries_piezometry: Annotated[bool, Profile.USER] = Field(
        True,
        description="Draw the observed groundwater-level series of the piezometers, in metres.",
    )
    climatic_summary: Annotated[bool, Profile.USER] = Field(
        True,
        description="Draw the monthly means of precipitation and ETP as bars.",
    )
    timeseries_intermittency: Annotated[bool, Profile.USER] = Field(
        True,
        description="Draw the flow states observed by the ONDE network at its stations.",
    )
    timeseries_water_quality: Annotated[bool, Profile.USER] = Field(
        True,
        description="Draw the water-quality series, one panel per measured parameter.",
    )
    station_inventory: Annotated[bool, Profile.USER] = Field(
        True,
        description="Draw the table of every station: type, id, coordinates and period.",
    )


class OverviewConfig(HydroModelBase):
    """Overview report settings (watershed identity card)."""

    name: Annotated[str, Profile.USER] = Field(
        "",
        description=(
            "Name of the watershed shown in the titles of the report. Unset, the "
            "catchment name of the workspace is used."
        ),
    )
    date_start: Annotated[IsoDateStr, Profile.USER] = Field(
        None,
        description=(
            "Start of the overview window (ISO date, e.g. '2019-01-01'). Overview "
            "mode has no [simulation.time], so this is the date declaration every "
            "[data.<type>] section without a window of its own inherits. Must be "
            "declared together with date_end."
        ),
        examples=["2019-01-01"],
    )
    date_end: Annotated[IsoDateStr, Profile.USER] = Field(
        None,
        description=(
            "End of the overview window (ISO date, e.g. '2025-12-31'). Overview "
            "mode has no [simulation.time], so this is the date declaration every "
            "[data.<type>] section without a window of its own inherits. Must be "
            "declared together with date_start."
        ),
        examples=["2025-12-31"],
    )
    regional_context_label: Annotated[str | None, Profile.USER] = Field(
        None,
        description="Label used for the regional location figure.",
    )
    panels: Annotated[OverviewPanelsConfig, Profile.USER] = Field(
        default_factory=OverviewPanelsConfig,
        description="Panel toggles.",
    )

    @model_validator(mode="after")
    def _check_date_window(self):
        if bool(self.date_start) != bool(self.date_end):
            missing = "date_end" if self.date_start else "date_start"
            raise ValueError(
                f"overview.{missing} is missing: declare date_start and date_end together"
            )
        if self.date_start and self.date_end:
            from datetime import datetime

            if datetime.fromisoformat(self.date_start) >= datetime.fromisoformat(self.date_end):
                raise ValueError("overview.date_start must be before overview.date_end")
        return self
