"""Wind manager: custom files and SIM2."""

from __future__ import annotations

from hydromodpy.data.common.clients.sim2_products import sim2_source
from hydromodpy.data.managers.base_manager_field import BaseFieldManager


class WindManager(BaseFieldManager):
    VARIABLE_NAME = "wind"
    INTERNAL_UNIT = "m/s"
    SOURCES = {"sim2": sim2_source("wind")}
