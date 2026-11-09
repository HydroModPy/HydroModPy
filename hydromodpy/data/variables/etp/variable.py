"""ETP variable: custom files, SIM2 and Explore2."""

from __future__ import annotations

from hydromodpy.data.families.grids import GridVariable


class EtpVariable(GridVariable):
    VARIABLE_NAME = "etp"
    INTERNAL_UNIT = "mm/day"
