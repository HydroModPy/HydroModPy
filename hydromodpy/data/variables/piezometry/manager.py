"""Piezometry manager: orchestrates custom and API loading."""

from __future__ import annotations

from hydromodpy.data.base_manager_variable import BaseVariableManager
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.variables.piezometry.config import PiezometrySourceConfig


class PiezometryManager(BaseVariableManager):
    VARIABLE_NAME = "piezometry"
    INTERNAL_UNIT = "m"

    def _fetch_from_source(self, source_cfg: PiezometrySourceConfig) -> list[PointRecord]:
        if source_cfg.source == "custom":
            from hydromodpy.data.variables.piezometry.custom import load_custom

            records = load_custom(source_cfg, project_period=self.project_period)
            return self._apply_mask(records, source_cfg)
        elif source_cfg.source == "hubeau":
            return self._fetch_hubeau(source_cfg)
        raise ValueError(f"Unknown piezometry source: {source_cfg.source}")

    def _fetch_hubeau(self, source_cfg: PiezometrySourceConfig) -> list[PointRecord]:
        from hydromodpy.data.common.clients.hubeau_cache import fetch_with_smart_cache
        from hydromodpy.data.variables.piezometry.apis.hubeau import fetch

        nearest_to = self._resolve_nearest_to(source_cfg) if source_cfg.nearest else None

        def _fetch_for(sids, start, end):
            return fetch(
                product=source_cfg.product,
                bbox=self._resolve_bbox(source_cfg),
                station_ids=sids,
                date_start=start,
                date_end=end,
                nearest_to=nearest_to,
                require_observations=source_cfg.require_observations,
                fallback_search_radius_km=source_cfg.fallback_search_radius_km,
            )

        return fetch_with_smart_cache(
            self,
            source_cfg=source_cfg,
            fetch_fn=_fetch_for,
        )
