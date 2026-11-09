"""Humidity variable: custom files and SIM2."""

from __future__ import annotations

from hydromodpy.data.families.grids import GridVariable


class HumidityVariable(GridVariable):
    VARIABLE_NAME = "humidity"
    INTERNAL_UNIT = "%"
