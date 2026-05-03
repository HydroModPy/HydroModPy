"""Soil moisture manager: custom and SIM2."""

from __future__ import annotations

from hydromodpy.data.variables._sim2_field_manager import Sim2BackedFieldManager


class SoilMoistureManager(Sim2BackedFieldManager):
    VARIABLE_NAME = "soil_moisture"
    INTERNAL_UNIT = "%"
