"""Wind manager: custom and SIM2."""

from __future__ import annotations

from hydromodpy.data.variables._sim2_field_manager import Sim2BackedFieldManager


class WindManager(Sim2BackedFieldManager):
    VARIABLE_NAME = "wind"
    INTERNAL_UNIT = "m/s"
