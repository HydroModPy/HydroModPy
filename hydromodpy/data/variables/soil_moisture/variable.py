"""Soil moisture variable: custom files and SIM2."""

from __future__ import annotations

from hydromodpy.data.families.grids import GridVariable


class SoilMoistureVariable(GridVariable):
    VARIABLE_NAME = "soil_moisture"
    INTERNAL_UNIT = "%"
