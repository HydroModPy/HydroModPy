"""Wind manager: custom files and SIM2."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_field import BaseFieldManager


class WindManager(BaseFieldManager):
    VARIABLE_NAME = "wind"
    INTERNAL_UNIT = "m/s"
