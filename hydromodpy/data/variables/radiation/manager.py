"""Radiation manager: orchestrates custom and SIM2 API loading."""

from __future__ import annotations

from hydromodpy.data.base_manager_field import BaseFieldManager
from hydromodpy.data.variables.radiation.config import RadiationSourceConfig


class RadiationManager(BaseFieldManager):
    """Multi-source radiation manager.

    Combines atmospheric (DLI_Q) and visible (SSI_Q) radiation from SIM2,
    or loads custom radiation data as PointRecords.
    """

    VARIABLE_NAME = "radiation"
    INTERNAL_UNIT = "MJ/m2/j"

    def _fetch_from_source(self, source_cfg: RadiationSourceConfig):
        if source_cfg.source == "custom":
            from hydromodpy.data.variables.radiation.custom import load_custom

            records = load_custom(
                source_cfg, project_period=self.project_period, internal_unit=self.INTERNAL_UNIT
            )
            return self._handle_custom_results(records, source_cfg)
        elif source_cfg.source == "sim2":
            from hydromodpy.data.variables.radiation.apis.sim2 import fetch

            variable_names = [f"radiation_{c}" for c in source_cfg.components]
            return self._load_or_fetch_fields(
                source_cfg,
                "sim2",
                fetch,
                variable_names=variable_names,
            )
        raise ValueError(f"Unknown radiation source: {source_cfg.source}")
