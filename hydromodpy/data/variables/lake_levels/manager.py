"""Lake-levels manager: custom chronicles."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_variable import BaseVariableManager


class LakeLevelsManager(BaseVariableManager):
    VARIABLE_NAME = "lake_levels"
    INTERNAL_UNIT = "m"
    RECORD_VARIABLE = "lake_level"
