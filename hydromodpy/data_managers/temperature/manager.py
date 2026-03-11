"""Temperature manager: orchestrates custom and SIM2 API loading."""

from __future__ import annotations

from hydromodpy.data_managers.common.base_field_manager import BaseFieldManager
from hydromodpy.data_managers.temperature.config import TemperatureConfig, TemperatureSourceConfig


class TemperatureManager(BaseFieldManager):
    """Multi-source temperature manager."""

    VARIABLE_NAME = "temperature"
    INTERNAL_UNIT = "degC"

    def _fetch_from_source(self, source_cfg: TemperatureSourceConfig):
        if source_cfg.source == "custom":
            from hydromodpy.data_managers.temperature.custom import load_custom
            records = load_custom(
                source_cfg,
                project_period=self.project_period,
                internal_unit=self.INTERNAL_UNIT,
            )
            return self._handle_custom_results(records, source_cfg)
        elif source_cfg.source == "sim2":
            from hydromodpy.data_managers.temperature.apis.sim2 import fetch
            return self._load_or_fetch_fields(source_cfg, "sim2", fetch)
        raise ValueError(f"Unknown temperature source: {source_cfg.source}")
