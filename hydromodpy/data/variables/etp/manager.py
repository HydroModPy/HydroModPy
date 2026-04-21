"""ETP manager: orchestrates custom and SIM2 API loading."""

from __future__ import annotations

from hydromodpy.data.base_manager import BaseFieldManager
from hydromodpy.data.variables.etp.config import EtpSourceConfig


class EtpManager(BaseFieldManager):
    """Multi-source ETP manager."""

    VARIABLE_NAME = "etp"
    INTERNAL_UNIT = "mm/day"

    def _fetch_from_source(self, source_cfg: EtpSourceConfig):
        if source_cfg.source == "custom":
            from hydromodpy.data.variables.etp.custom import load_custom
            records = load_custom(
                source_cfg,
                project_period=self.project_period,
                internal_unit=self.INTERNAL_UNIT,
            )
            return self._handle_custom_results(records, source_cfg)
        elif source_cfg.source == "sim2":
            from hydromodpy.data.variables.etp.apis.sim2 import fetch
            return self._load_or_fetch_fields(source_cfg, "sim2", fetch)
        raise ValueError(f"Unknown etp source: {source_cfg.source}")
