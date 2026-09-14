"""Lake-levels manager: orchestrates custom chronicle loading."""

from __future__ import annotations

from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.managers.base_manager_variable import BaseVariableManager
from hydromodpy.data.variables.lake_levels.config import LakeLevelsSourceConfig


class LakeLevelsManager(BaseVariableManager):
    VARIABLE_NAME = "lake_levels"
    INTERNAL_UNIT = "m"

    def _fetch_from_source(self, source_cfg: LakeLevelsSourceConfig) -> list[PointRecord]:
        if source_cfg.source == "custom":
            from hydromodpy.data.variables.lake_levels.custom import load_custom

            records = load_custom(source_cfg, project_period=self.project_period)
            return self._apply_mask(records, source_cfg)
        raise ValueError(f"Unknown lake_levels source: {source_cfg.source}")
