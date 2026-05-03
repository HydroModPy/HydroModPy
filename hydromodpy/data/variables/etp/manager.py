"""ETP manager: custom and SIM2."""

from __future__ import annotations

from hydromodpy.data.variables._sim2_field_manager import Sim2BackedFieldManager


class EtpManager(Sim2BackedFieldManager):
    VARIABLE_NAME = "etp"
    INTERNAL_UNIT = "mm/day"
