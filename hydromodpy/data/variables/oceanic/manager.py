"""Oceanic manager: custom files, SHOM tide gauges, or a constant sea level."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_field import BaseFieldManager
from hydromodpy.data.variables.oceanic import constant
from hydromodpy.data.variables.oceanic.apis import shom


class OceanicManager(BaseFieldManager):
    """Sea level from the user's files, the nearest SHOM gauge, or a constant."""

    VARIABLE_NAME = "oceanic"
    INTERNAL_UNIT = "m"
    SOURCES = {"shom": shom.fetch_for_config, "constant": constant.fetch}
