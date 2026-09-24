"""Lake-outflow manager: custom chronicles."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_variable import BaseVariableManager


class LakeOutflowManager(BaseVariableManager):
    VARIABLE_NAME = "lake_outflow"
    INTERNAL_UNIT = "m3/s"
