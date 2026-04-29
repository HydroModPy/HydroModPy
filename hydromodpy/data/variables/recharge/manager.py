"""Recharge manager: custom, SIM2 EDR, and synthetic generation."""

from __future__ import annotations

from typing import Any

from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables._sim2_field_manager import Sim2BackedFieldManager


class RechargeManager(Sim2BackedFieldManager):
    VARIABLE_NAME = "recharge"
    INTERNAL_UNIT = "mm/day"

    def _fetch_from_source(self, source_cfg: Any) -> list[FieldRecord | PointRecord]:
        if source_cfg.source == "synthetic":
            from hydromodpy.data.variables.recharge.synthetic import generate

            return generate(source_cfg, project_period=self.project_period)
        return super()._fetch_from_source(source_cfg)
