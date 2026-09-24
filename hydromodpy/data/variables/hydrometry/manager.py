"""Hydrometry manager: custom chronicles and Hub'Eau."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_variable import BaseVariableManager
from hydromodpy.data.variables.hydrometry.apis import hubeau


class HydrometryManager(BaseVariableManager):
    VARIABLE_NAME = "hydrometry"
    INTERNAL_UNIT = "m3/s"
    RECORD_VARIABLE = "discharge"
    SOURCES = {"hubeau": hubeau.fetch_for_config}
