"""Humidity manager: orchestrates custom and SIM2 API loading."""

from __future__ import annotations

from hydromodpy.data.base_manager_field import BaseFieldManager
from hydromodpy.data.variables.humidity.config import HumiditySourceConfig


class HumidityManager(BaseFieldManager):
    """Multi-source humidity manager."""

    VARIABLE_NAME = "humidity"
    INTERNAL_UNIT = "%"

    def _fetch_from_source(self, source_cfg: HumiditySourceConfig):
        if source_cfg.source == "custom":
            from hydromodpy.data.variables.humidity.custom import load_custom

            records = load_custom(
                source_cfg,
                project_period=self.project_period,
                internal_unit=self.INTERNAL_UNIT,
            )
            return self._handle_custom_results(records, source_cfg)
        elif source_cfg.source == "sim2":
            from hydromodpy.data.variables.humidity.apis.sim2 import fetch

            return self._load_or_fetch_fields(source_cfg, "sim2", fetch)
        raise ValueError(f"Unknown humidity source: {source_cfg.source}")
