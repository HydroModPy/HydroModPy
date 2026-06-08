"""Lake-outflow manager: orchestrates custom chronicle loading."""

from __future__ import annotations

from hydromodpy.data.base_manager_variable import BaseVariableManager
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.lake_outflow.config import LakeOutflowSourceConfig


class LakeOutflowManager(BaseVariableManager):
    VARIABLE_NAME = "lake_outflow"
    INTERNAL_UNIT = "m3/s"

    def _fetch_from_source(self, source_cfg: LakeOutflowSourceConfig) -> list[PointRecord]:
        if source_cfg.source == "custom":
            from hydromodpy.data.variables.lake_outflow.custom import load_custom

            records = load_custom(source_cfg, project_period=self.project_period)
            return self._apply_mask(records, source_cfg)
        raise ValueError(f"Unknown lake_outflow source: {source_cfg.source}")
