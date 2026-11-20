"""Water quality variable: custom chronicles and Hub'Eau."""

from __future__ import annotations

from hydromodpy.data.families.stations import StationVariable


class WaterQualityVariable(StationVariable):
    """Water quality analyses, from the user's files or Hub'Eau."""

    VARIABLE_NAME = "water_quality"
    INTERNAL_UNIT = "mg/L"
