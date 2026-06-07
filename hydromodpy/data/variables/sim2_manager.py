"""Generic field manager for variables backed by SIM2 and custom sources."""

from __future__ import annotations

import importlib
from typing import Any, ClassVar

from hydromodpy.data.base_manager_field import BaseFieldManager
from hydromodpy.data.contracts.spatial_field import FieldRecord
from hydromodpy.data.contracts.timeseries import PointRecord


class Sim2BackedFieldManager(BaseFieldManager):
    """Base class for variables loaded from custom sources and the SIM2 API."""

    SIM2_HAS_COMPONENTS: ClassVar[bool] = False
    SIM2_VARIABLE_NAMES: ClassVar[list[str] | None] = None

    def _fetch_from_source(self, source_cfg: Any) -> list[FieldRecord | PointRecord]:
        if source_cfg.source == "custom":
            return self._fetch_custom(source_cfg)
        if source_cfg.source == "sim2":
            return self._fetch_sim2(source_cfg)
        raise ValueError(f"Unknown {self.VARIABLE_NAME} source: {source_cfg.source}")

    def _fetch_custom(self, source_cfg: Any) -> list[FieldRecord | PointRecord]:
        module = importlib.import_module(f"hydromodpy.data.variables.{self.VARIABLE_NAME}.custom")
        records = module.load_custom(
            source_cfg,
            project_period=self.project_period,
            internal_unit=self.INTERNAL_UNIT,
        )
        return self._handle_custom_results(records, source_cfg)

    def _fetch_sim2(self, source_cfg: Any) -> list[FieldRecord]:
        module = importlib.import_module(
            f"hydromodpy.data.variables.{self.VARIABLE_NAME}.apis.sim2"
        )
        if self.SIM2_HAS_COMPONENTS:
            variable_names = [
                f"{self.VARIABLE_NAME}_{component}" for component in source_cfg.components
            ]
            return self._load_or_fetch_fields(
                source_cfg,
                "sim2",
                module.fetch,
                variable_names=variable_names,
            )
        return self._load_or_fetch_fields(
            source_cfg,
            "sim2",
            module.fetch,
            variable_names=self.SIM2_VARIABLE_NAMES,
        )


__all__ = ["Sim2BackedFieldManager"]
