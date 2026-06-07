"""ETP manager: custom and SIM2."""

from __future__ import annotations

from hydromodpy.data.variables.sim2_manager import Sim2BackedFieldManager


class EtpManager(Sim2BackedFieldManager):
    VARIABLE_NAME = "etp"
    INTERNAL_UNIT = "mm/day"
