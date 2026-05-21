"""Soil moisture manager: custom and SIM2."""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.data.variables.sim2_manager import Sim2BackedFieldManager


class SoilMoistureManager(Sim2BackedFieldManager):
    VARIABLE_NAME = "soil_moisture"
    SIM2_VARIABLE_NAMES: ClassVar[list[str]] = ["soil_moisture_index"]
    INTERNAL_UNIT = "%"
