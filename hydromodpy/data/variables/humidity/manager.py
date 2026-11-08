"""Humidity manager: custom files and SIM2."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_field import BaseFieldManager


class HumidityManager(BaseFieldManager):
    VARIABLE_NAME = "humidity"
    INTERNAL_UNIT = "%"
