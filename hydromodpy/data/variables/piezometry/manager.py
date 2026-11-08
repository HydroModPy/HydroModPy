"""Piezometry manager: custom chronicles and Hub'Eau."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_variable import BaseVariableManager


class PiezometryManager(BaseVariableManager):
    """Groundwater level and depth records, from the user's files or Hub'Eau."""

    VARIABLE_NAME = "piezometry"
    INTERNAL_UNIT = "m"
    RECORD_VARIABLE = "groundwater_level"
