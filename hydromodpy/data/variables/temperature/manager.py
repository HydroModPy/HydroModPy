"""Temperature manager: custom and SIM2."""

from __future__ import annotations

from hydromodpy.data.variables._sim2_field_manager import Sim2BackedFieldManager


class TemperatureManager(Sim2BackedFieldManager):
    VARIABLE_NAME = "temperature"
    INTERNAL_UNIT = "degC"
