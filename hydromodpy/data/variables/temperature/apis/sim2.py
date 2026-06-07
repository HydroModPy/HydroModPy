"""SIM2 EDR API adapter for temperature data."""

from __future__ import annotations

from datetime import datetime

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.variables.sim2 import Sim2FieldSpec, fetch_sim2_field
from hydromodpy.data.variables.temperature.config import TemperatureSourceConfig

SIM2_PARAMETER = "T_Q"
VARIABLE_NAME = "temperature"
INTERNAL_UNIT = "degC"
_SPEC = Sim2FieldSpec(
    parameter=SIM2_PARAMETER,
    variable=VARIABLE_NAME,
    unit=INTERNAL_UNIT,
)


def fetch(
    config: TemperatureSourceConfig,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Fetch temperature from SIM2 via the GéoSAS EDR API.

    Always returns the full spatial grid as a FieldRecord.
    """
    return fetch_sim2_field(_SPEC, bbox=bbox, project_period=project_period)
