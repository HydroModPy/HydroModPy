"""Precipitation manager: orchestrates custom and SIM2 API loading."""

from __future__ import annotations

from hydromodpy.data_managers.common.base_field_manager import BaseFieldManager
from hydromodpy.data_managers.precipitation.config import PrecipitationConfig, PrecipitationSourceConfig


class PrecipitationManager(BaseFieldManager):
    """Multi-source precipitation manager.

    Combines liquid (PRELIQ_Q) and solid (PRENEI_Q) precipitation from SIM2,
    or loads custom pluviometer data as PointRecords.
    """

    VARIABLE_NAME = "precipitation"
    INTERNAL_UNIT = "mm/day"

    def _fetch_from_source(self, source_cfg: PrecipitationSourceConfig):
        if source_cfg.source == "custom":
            from hydromodpy.data_managers.precipitation.custom import load_custom
            records = load_custom(source_cfg, project_period=self.project_period, internal_unit=self.INTERNAL_UNIT)
            return self._apply_mask(records, source_cfg)
        elif source_cfg.source == "sim2":
            from hydromodpy.data_managers.precipitation.apis.sim2 import fetch
            variable_names = [f"precipitation_{c}" for c in source_cfg.components]
            return self._load_or_fetch_fields(
                source_cfg, "sim2", fetch,
                variable_names=variable_names,
            )
        raise ValueError(f"Unknown precipitation source: {source_cfg.source}")
