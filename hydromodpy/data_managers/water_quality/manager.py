"""Water quality manager: orchestrates custom and API loading."""

from __future__ import annotations

from hydromodpy.data_managers.common.base_manager import BaseVariableManager
from hydromodpy.data_managers.contracts.timeseries import PointRecord
from hydromodpy.data_managers.water_quality.config import WaterQualityConfig, WaterQualitySourceConfig


class WaterQualityManager(BaseVariableManager):

    VARIABLE_NAME = "water_quality"
    INTERNAL_UNIT = "mg/L"

    def _fetch_from_source(self, source_cfg: WaterQualitySourceConfig) -> list[PointRecord]:
        if source_cfg.source == "custom":
            from hydromodpy.data_managers.water_quality.custom import load_custom
            records = load_custom(
                source_cfg, project_period=self.project_period,
                internal_unit=self.INTERNAL_UNIT,
            )
            return self._apply_mask(records, source_cfg)
        elif source_cfg.source == "hubeau":
            return self._fetch_hubeau(source_cfg)
        raise ValueError(f"Unknown water quality source: {source_cfg.source}")

    def _fetch_hubeau(self, source_cfg: WaterQualitySourceConfig) -> list[PointRecord]:
        """Fetch from Hub'Eau with cache support."""
        from hydromodpy.data_managers.water_quality.apis.hubeau import fetch

        if self.project_period is None:
            raise ValueError("project_period required for Hub'Eau.")

        # Try cache for explicitly requested station_ids
        if source_cfg.station_ids and not source_cfg.force_refresh:
            cached = []
            missing_ids = []
            for sid in source_cfg.station_ids:
                rec = self._load_cached_api_record(source="hubeau", station_id=sid)
                if rec is not None:
                    cached.append(rec)
                    print(f"  Hub'Eau cache hit: {sid}")
                else:
                    missing_ids.append(sid)
            if not missing_ids:
                return self._apply_mask(cached, source_cfg)
            bbox = self._resolve_bbox(source_cfg)
            records = fetch(
                site_type=source_cfg.site_type, bbox=bbox,
                station_ids=missing_ids,
                date_start=self.project_period[0], date_end=self.project_period[1],
                parameters=source_cfg.parameters,
            )
            self._persist_api_records(records, "hubeau")
            return self._apply_mask(cached + records, source_cfg)

        bbox = self._resolve_bbox(source_cfg)
        records = fetch(
            site_type=source_cfg.site_type, bbox=bbox,
            station_ids=source_cfg.station_ids,
            date_start=self.project_period[0], date_end=self.project_period[1],
            parameters=source_cfg.parameters,
        )
        self._persist_api_records(records, "hubeau")
        return self._apply_mask(records, source_cfg)

    def _resolve_bbox(self, source_cfg) -> tuple | None:
        if source_cfg.mask_path:
            from hydromodpy.data_managers.common.geo_helpers import load_mask_geometry, geometry_to_bbox
            geom = load_mask_geometry(source_cfg.mask_path)
            return geometry_to_bbox(geom)
        if source_cfg.extent and self.project_extent:
            return self.project_extent
        return None

    def _apply_mask(self, records: list[PointRecord], source_cfg) -> list[PointRecord]:
        if not source_cfg.mask_path:
            return records
        from hydromodpy.data_managers.common.geo_helpers import load_mask_geometry, filter_locations_by_geometry
        geom = load_mask_geometry(source_cfg.mask_path)
        locs_to_check = [r.location for r in records if r.location is not None]
        inside = filter_locations_by_geometry(locs_to_check, geom)
        valid_ids = {loc.id for loc in inside}
        return [r for r in records if r.location is None or r.station_id in valid_ids]
