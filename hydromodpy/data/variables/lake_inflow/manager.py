"""Lake-inflow manager: custom chronicles."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_variable import BaseVariableManager


class LakeInflowManager(BaseVariableManager):
    VARIABLE_NAME = "lake_inflow"
    INTERNAL_UNIT = "m3/s"
