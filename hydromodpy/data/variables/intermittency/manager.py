"""Intermittency manager: orchestrates custom and Hub'Eau ONDE loading."""

from __future__ import annotations

from hydromodpy.data.common.base_manager import BaseVariableManager
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.intermittency.config import (
    IntermittencySourceConfig,
)


class IntermittencyManager(BaseVariableManager):

    VARIABLE_NAME = "intermittency"
    INTERNAL_UNIT = "code"

    def _fetch_from_source(self, source_cfg: IntermittencySourceConfig) -> list[PointRecord]:
        if source_cfg.source == "custom":
            from hydromodpy.data.variables.intermittency.custom import load_custom
            records = load_custom(source_cfg, project_period=self.project_period)
            return self._apply_mask(records, source_cfg)
        elif source_cfg.source == "hubeau":
            return self._fetch_hubeau(source_cfg)
        raise ValueError(f"Unknown intermittency source: {source_cfg.source}")

    def _fetch_hubeau(self, source_cfg: IntermittencySourceConfig) -> list[PointRecord]:
        from hydromodpy.data.common.clients.hubeau_cache import fetch_with_smart_cache
        from hydromodpy.data.variables.intermittency.apis.hubeau import fetch

        def _fetch_for(sids, start, end):
            return fetch(
                bbox=self._resolve_bbox(source_cfg),
                station_ids=sids, date_start=start, date_end=end,
                code_departement=source_cfg.code_departement,
                require_observations=source_cfg.require_observations,
                fallback_search_radius_km=source_cfg.fallback_search_radius_km,
            )

        return fetch_with_smart_cache(
            self, source_cfg=source_cfg, fetch_fn=_fetch_for,
        )
