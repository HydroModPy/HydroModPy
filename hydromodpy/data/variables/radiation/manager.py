"""Radiation manager: custom and SIM2 (atmospheric + visible components)."""

from __future__ import annotations

from hydromodpy.data.variables.sim2_manager import Sim2BackedFieldManager


class RadiationManager(Sim2BackedFieldManager):
    VARIABLE_NAME = "radiation"
    INTERNAL_UNIT = "MJ/m2/j"
    SIM2_HAS_COMPONENTS = True
