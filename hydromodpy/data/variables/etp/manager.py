"""ETP manager: custom files, SIM2 and Explore2."""

from __future__ import annotations

from hydromodpy.data.common.clients.explore2_files import explore2_source
from hydromodpy.data.common.clients.sim2_products import sim2_source
from hydromodpy.data.managers.base_manager_field import BaseFieldManager


class EtpManager(BaseFieldManager):
    VARIABLE_NAME = "etp"
    INTERNAL_UNIT = "mm/day"
    SOURCES = {"sim2": sim2_source("etp"), "explore2": explore2_source("etp")}
