"""SIM2 EDR API adapter for runoff data."""

from __future__ import annotations

from datetime import datetime

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.variables.runoff.config import RunoffSourceConfig
from hydromodpy.data.variables.sim2 import Sim2FieldSpec, fetch_sim2_field

SIM2_PARAMETER = "RUNC_Q"
VARIABLE_NAME = "runoff"
INTERNAL_UNIT = "mm/day"
_SPEC = Sim2FieldSpec(
    parameter=SIM2_PARAMETER,
    variable=VARIABLE_NAME,
    unit=INTERNAL_UNIT,
)


def fetch(
    config: RunoffSourceConfig,
    *,
    bbox: tuple[float, float, float, float] | None = None,
    project_period: tuple[datetime, datetime] | None = None,
) -> list[FieldRecord]:
    """Fetch runoff from SIM2 via the GéoSAS EDR API.

    Always returns the full spatial grid as a FieldRecord.
    """
    return fetch_sim2_field(_SPEC, bbox=bbox, project_period=project_period)
