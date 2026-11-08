"""ETP manager: custom files, SIM2 and Explore2."""

from __future__ import annotations

from hydromodpy.data.managers.base_manager_field import BaseFieldManager


class EtpManager(BaseFieldManager):
    VARIABLE_NAME = "etp"
    INTERNAL_UNIT = "mm/day"
