"""Lake-withdrawal manager: custom chronicles."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_variable import BaseVariableManager


class LakeWithdrawalManager(BaseVariableManager):
    VARIABLE_NAME = "lake_withdrawal"
    INTERNAL_UNIT = "m3/s"
