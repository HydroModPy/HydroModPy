"""Radiation variable: custom files and SIM2."""

from __future__ import annotations

from hydromodpy.data.families.grids import GridVariable


class RadiationVariable(GridVariable):
    VARIABLE_NAME = "radiation"
    INTERNAL_UNIT = "MJ/m2/j"
