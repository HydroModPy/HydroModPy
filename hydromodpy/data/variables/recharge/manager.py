"""Recharge manager: custom files, SIM2, and a synthetic series."""

from __future__ import annotations

from hydromodpy.data.common.clients.sim2_products import sim2_source
from hydromodpy.data.managers.base_manager_field import BaseFieldManager
from hydromodpy.data.variables.recharge import synthetic


class RechargeManager(BaseFieldManager):
    VARIABLE_NAME = "recharge"
    INTERNAL_UNIT = "mm/day"
    SOURCES = {"sim2": sim2_source("recharge"), "synthetic": synthetic.fetch}
