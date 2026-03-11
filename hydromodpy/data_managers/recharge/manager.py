"""Recharge manager: orchestrates custom, SIM2 API, and synthetic loading."""

from __future__ import annotations

from hydromodpy.data_managers.common.base_field_manager import BaseFieldManager
from hydromodpy.data_managers.recharge.config import RechargeConfig, RechargeSourceConfig


class RechargeManager(BaseFieldManager):
    """Multi-source recharge manager.

    Loads recharge data from custom CSV, SIM2 EDR API, or synthetic generation.
    Returns PointRecord for point/mean data, FieldRecord for gridded.
    """

    VARIABLE_NAME = "recharge"
    INTERNAL_UNIT = "mm/day"

    def _fetch_from_source(self, source_cfg: RechargeSourceConfig):
        if source_cfg.source == "custom":
            from hydromodpy.data_managers.recharge.custom import load_custom
            records = load_custom(
                source_cfg,
                project_period=self.project_period,
                internal_unit=self.INTERNAL_UNIT,
            )
            return self._apply_mask(records, source_cfg)
        elif source_cfg.source == "sim2":
            from hydromodpy.data_managers.recharge.apis.sim2 import fetch
            return self._load_or_fetch_fields(source_cfg, "sim2", fetch)
        elif source_cfg.source == "synthetic":
            from hydromodpy.data_managers.recharge.synthetic import generate
            return generate(source_cfg, project_period=self.project_period)
        raise ValueError(f"Unknown recharge source: {source_cfg.source}")
