"""Piezometry variable: custom chronicles and Hub'Eau."""

from __future__ import annotations

from hydromodpy.data.families.stations import StationVariable


class PiezometryVariable(StationVariable):
    """Groundwater level and depth records, from the user's files or Hub'Eau."""

    VARIABLE_NAME = "piezometry"
    INTERNAL_UNIT = "m"
    RECORD_VARIABLE = "groundwater_level"
