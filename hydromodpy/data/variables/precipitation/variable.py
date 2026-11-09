"""Precipitation variable: custom files, SIM2 and Explore2."""

from __future__ import annotations

from hydromodpy.data.families.grids import GridVariable


class PrecipitationVariable(GridVariable):
    VARIABLE_NAME = "precipitation"
    INTERNAL_UNIT = "mm/day"
