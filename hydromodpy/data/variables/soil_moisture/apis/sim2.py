"""SIM2 EDR API adapter for soil moisture data."""

from __future__ import annotations

from datetime import datetime

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.variables.sim2 import Sim2FieldSpec, fetch_sim2_field
from hydromodpy.data.variables.soil_moisture.config import SoilMoistureSourceConfig

SIM2_PARAMETER = "SWI_Q"
VARIABLE_NAME = "soil_moisture_index"
INTERNAL_UNIT = "%"
_SPEC = Sim2FieldSpec(
    parameter=SIM2_PARAMETER,
    variable=VARIABLE_NAME,
    unit=INTERNAL_UNIT,
)


def fetch(
    config: SoilMoistureSourceConfig,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Fetch soil moisture index from SIM2 via the GeoSAS EDR API.

    Always returns the full spatial grid as a FieldRecord.
    """
    return fetch_sim2_field(_SPEC, bbox=bbox, project_period=project_period)
