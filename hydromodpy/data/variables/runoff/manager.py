"""Runoff manager: custom files and SIM2."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_field import BaseFieldManager


class RunoffManager(BaseFieldManager):
    VARIABLE_NAME = "runoff"
    INTERNAL_UNIT = "mm/day"
