"""Water quality manager: custom chronicles and Hub'Eau."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_variable import BaseVariableManager


class WaterQualityManager(BaseVariableManager):
    """Water quality analyses, from the user's files or Hub'Eau."""

    VARIABLE_NAME = "water_quality"
    INTERNAL_UNIT = "mg/L"
