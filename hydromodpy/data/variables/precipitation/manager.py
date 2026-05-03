"""Precipitation manager: custom and SIM2 (liquid + solid components)."""

from __future__ import annotations

from hydromodpy.data.variables._sim2_field_manager import Sim2BackedFieldManager


class PrecipitationManager(Sim2BackedFieldManager):
    VARIABLE_NAME = "precipitation"
    INTERNAL_UNIT = "mm/day"
    SIM2_HAS_COMPONENTS = True
