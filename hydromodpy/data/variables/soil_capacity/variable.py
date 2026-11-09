"""Soil capacity variable: RU (available water capacity) rasters from the user's files."""

from __future__ import annotations

from hydromodpy.data.families.files import RasterFileVariable


class SoilCapacityVariable(RasterFileVariable):
    VARIABLE_NAME = "soil_capacity"
    INTERNAL_UNIT = "mm"
