"""Temperature variable: custom files and SIM2."""

from __future__ import annotations

from hydromodpy.data.families.grids import GridVariable


class TemperatureVariable(GridVariable):
    VARIABLE_NAME = "temperature"
    INTERNAL_UNIT = "degC"
