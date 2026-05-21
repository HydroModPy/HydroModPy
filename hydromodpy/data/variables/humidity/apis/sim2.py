"""SIM2 EDR API adapter for humidity data."""

from __future__ import annotations

from datetime import datetime

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.variables.humidity.config import HumiditySourceConfig
from hydromodpy.data.variables.sim2 import Sim2FieldSpec, fetch_sim2_field

SIM2_PARAMETER = "HU_Q"
VARIABLE_NAME = "humidity"
INTERNAL_UNIT = "%"
_SPEC = Sim2FieldSpec(
    parameter=SIM2_PARAMETER,
    variable=VARIABLE_NAME,
    unit=INTERNAL_UNIT,
)


def fetch(
    config: HumiditySourceConfig,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Fetch humidity from SIM2 via the GéoSAS EDR API.

    Always returns the full spatial grid as a FieldRecord.
    """
    return fetch_sim2_field(_SPEC, bbox=bbox, project_period=project_period)
