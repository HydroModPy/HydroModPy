"""SIM2 EDR API adapter for radiation data."""

from __future__ import annotations

from datetime import datetime

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.variables.radiation.config import RadiationSourceConfig
from hydromodpy.data.variables.sim2 import Sim2ComponentSpec, fetch_sim2_components

VARIABLE_NAME = "radiation"
INTERNAL_UNIT = "MJ/m2/j"

# 1 J/cm² = 1e4 J/m² = 0.01 MJ/m²
_JCMM2_TO_MJ_M2 = 0.01
_SPECS = {
    "atmospheric": Sim2ComponentSpec(
        component="atmospheric",
        parameter="DLI_Q",
        variable="radiation_atmospheric",
        unit=INTERNAL_UNIT,
        scale=_JCMM2_TO_MJ_M2,
    ),
    "visible": Sim2ComponentSpec(
        component="visible",
        parameter="SSI_Q",
        variable="radiation_visible",
        unit=INTERNAL_UNIT,
        scale=_JCMM2_TO_MJ_M2,
    ),
}


def fetch(
    config: RadiationSourceConfig,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Fetch radiation from SIM2 via the GeoSAS EDR API.

    Always returns the full spatial grid as FieldRecord(s), one per component.
    """
    return fetch_sim2_components(
        config.components,
        specs=_SPECS,
        bbox=bbox,
        project_period=project_period,
    )
