"""Temperature manager: custom files and SIM2."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_field import BaseFieldManager


class TemperatureManager(BaseFieldManager):
    VARIABLE_NAME = "temperature"
    INTERNAL_UNIT = "degC"
