"""SIM2 EDR API adapter for precipitation data."""

from __future__ import annotations

from datetime import datetime

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.variables.precipitation.config import PrecipitationSourceConfig
from hydromodpy.data.variables.sim2 import Sim2ComponentSpec, fetch_sim2_components

VARIABLE_NAME = "precipitation"
INTERNAL_UNIT = "mm/day"
_SPECS = {
    "liquid": Sim2ComponentSpec(
        component="liquid",
        parameter="PRELIQ_Q",
        variable="precipitation_liquid",
        unit=INTERNAL_UNIT,
    ),
    "solid": Sim2ComponentSpec(
        component="solid",
        parameter="PRENEI_Q",
        variable="precipitation_solid",
        unit=INTERNAL_UNIT,
    ),
    "total": Sim2ComponentSpec(
        component="total",
        parameter="PRELIQ_Q",
        parameters=("PRELIQ_Q", "PRENEI_Q"),
        variable="precipitation_total",
        unit=INTERNAL_UNIT,
    ),
}


def _transform_component(component: str, ds: object) -> object:
    if component == "total":
        return ds["PRELIQ_Q"] + ds["PRENEI_Q"]
    return ds[_SPECS[component].parameter]


def fetch(
    config: PrecipitationSourceConfig,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Fetch precipitation from SIM2 via the GéoSAS EDR API.

    Always returns the full spatial grid as FieldRecord(s), one per component.
    """
    return fetch_sim2_components(
        config.components,
        specs=_SPECS,
        bbox=bbox,
        project_period=project_period,
        transform=_transform_component,
    )
