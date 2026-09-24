"""Piezometry manager: custom chronicles and Hub'Eau."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_variable import BaseVariableManager
from hydromodpy.data.variables.piezometry.apis import hubeau


class PiezometryManager(BaseVariableManager):
    VARIABLE_NAME = "piezometry"
    INTERNAL_UNIT = "m"
    RECORD_VARIABLE = "groundwater_level"
    SOURCES = {"hubeau": hubeau.fetch_for_config}
