"""Recharge variable: custom files, SIM2, and a synthetic series."""

from __future__ import annotations

from hydromodpy.data.families.grids import GridVariable


class RechargeVariable(GridVariable):
    VARIABLE_NAME = "recharge"
    INTERNAL_UNIT = "mm/day"
