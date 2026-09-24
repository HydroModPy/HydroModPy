"""Water quality manager: custom chronicles and Hub'Eau."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_variable import BaseVariableManager
from hydromodpy.data.variables.water_quality.apis import hubeau


class WaterQualityManager(BaseVariableManager):
    VARIABLE_NAME = "water_quality"
    INTERNAL_UNIT = "mg/L"
    SOURCES = {"hubeau": hubeau.fetch_for_config}
