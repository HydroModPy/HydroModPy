"""Lake-outflow variable: custom chronicles."""

from __future__ import annotations

from hydromodpy.data.families.stations import StationVariable


class LakeOutflowVariable(StationVariable):
    VARIABLE_NAME = "lake_outflow"
    INTERNAL_UNIT = "m3/s"
