"""Lake-inflow variable: custom chronicles."""

from __future__ import annotations

from hydromodpy.data.families.stations import StationVariable


class LakeInflowVariable(StationVariable):
    VARIABLE_NAME = "lake_inflow"
    INTERNAL_UNIT = "m3/s"
