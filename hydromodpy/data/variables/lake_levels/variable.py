"""Lake-levels variable: custom chronicles."""

from __future__ import annotations

from hydromodpy.data.families.stations import StationVariable


class LakeLevelsVariable(StationVariable):
    VARIABLE_NAME = "lake_levels"
    INTERNAL_UNIT = "m"
    RECORD_VARIABLE = "lake_level"
