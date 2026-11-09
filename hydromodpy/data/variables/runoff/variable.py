"""Runoff variable: custom files and SIM2."""

from __future__ import annotations

from hydromodpy.data.families.grids import GridVariable


class RunoffVariable(GridVariable):
    VARIABLE_NAME = "runoff"
    INTERNAL_UNIT = "mm/day"
