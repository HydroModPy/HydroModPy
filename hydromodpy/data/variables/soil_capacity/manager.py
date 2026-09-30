"""Soil capacity manager: RU (available water capacity) rasters from the user's files."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_file import RasterFileManager


class SoilCapacityManager(RasterFileManager):
    VARIABLE_NAME = "soil_capacity"
    INTERNAL_UNIT = "mm"
