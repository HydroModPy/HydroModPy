"""Runoff manager: orchestrates custom and SIM2 API loading."""

from __future__ import annotations

from hydromodpy.data.common.base_manager import BaseFieldManager
from hydromodpy.data.variables.runoff.config import RunoffSourceConfig


class RunoffManager(BaseFieldManager):
    """Multi-source runoff manager."""

    VARIABLE_NAME = "runoff"
    INTERNAL_UNIT = "mm/day"

    def _fetch_from_source(self, source_cfg: RunoffSourceConfig):
        if source_cfg.source == "custom":
            from hydromodpy.data.variables.runoff.custom import load_custom
            records = load_custom(
                source_cfg,
                project_period=self.project_period,
                internal_unit=self.INTERNAL_UNIT,
            )
            return self._handle_custom_results(records, source_cfg)
        elif source_cfg.source == "sim2":
            from hydromodpy.data.variables.runoff.apis.sim2 import fetch
            return self._load_or_fetch_fields(source_cfg, "sim2", fetch)
        raise ValueError(f"Unknown runoff source: {source_cfg.source}")
