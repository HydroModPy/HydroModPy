"""Precipitation manager: custom files, SIM2 and Explore2."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_field import BaseFieldManager


class PrecipitationManager(BaseFieldManager):
    VARIABLE_NAME = "precipitation"
    INTERNAL_UNIT = "mm/day"
