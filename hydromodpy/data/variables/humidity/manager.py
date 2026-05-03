"""Humidity manager: custom and SIM2."""

from __future__ import annotations

from hydromodpy.data.variables._sim2_field_manager import Sim2BackedFieldManager


class HumidityManager(Sim2BackedFieldManager):
    VARIABLE_NAME = "humidity"
    INTERNAL_UNIT = "%"
