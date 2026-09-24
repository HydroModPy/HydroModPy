"""Soil moisture manager: custom files and SIM2."""

from __future__ import annotations

from hydromodpy.data.common.clients.sim2_products import sim2_source
from hydromodpy.data.managers.base_manager_field import BaseFieldManager


class SoilMoistureManager(BaseFieldManager):
    VARIABLE_NAME = "soil_moisture"
    INTERNAL_UNIT = "%"
    SOURCES = {"sim2": sim2_source("soil_moisture")}
