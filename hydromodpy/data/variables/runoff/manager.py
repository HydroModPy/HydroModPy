"""Runoff manager: custom and SIM2."""

from __future__ import annotations

from hydromodpy.data.variables.sim2_manager import Sim2BackedFieldManager


class RunoffManager(Sim2BackedFieldManager):
    VARIABLE_NAME = "runoff"
    INTERNAL_UNIT = "mm/day"
