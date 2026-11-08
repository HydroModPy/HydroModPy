"""Recharge manager: custom files, SIM2, and a synthetic series."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_field import BaseFieldManager


class RechargeManager(BaseFieldManager):
    VARIABLE_NAME = "recharge"
    INTERNAL_UNIT = "mm/day"
