"""Water quality manager: orchestrates custom and API loading."""

from __future__ import annotations

from hydromodpy.data_managers.common.base_manager import BaseVariableManager
from hydromodpy.data_managers.contracts.timeseries import PointRecord
from hydromodpy.data_managers.water_quality.config import WaterQualityConfig, WaterQualitySourceConfig


class WaterQualityManager(BaseVariableManager):

    VARIABLE_NAME = "water_quality"

    def _fetch_from_source(self, source_cfg: WaterQualitySourceConfig) -> list[PointRecord]:
        if source_cfg.source == "custom":
            from hydromodpy.data_managers.water_quality.custom import load_custom
            records = load_custom(source_cfg, project_period=self.project_period)
            return self._apply_mask(records, source_cfg)
        elif source_cfg.source == "hubeau":
            from hydromodpy.data_managers.water_quality.apis.hubeau import fetch
            if self.project_period is None:
                raise ValueError("project_period required for Hub'Eau.")
            bbox = self._resolve_bbox(source_cfg)
            records = fetch(
                site_type=source_cfg.site_type, bbox=bbox,
                station_ids=source_cfg.station_ids,
                date_start=self.project_period[0], date_end=self.project_period[1],
                parameters=source_cfg.parameters,
            )
            return self._apply_mask(records, source_cfg)
        raise ValueError(f"Unknown water quality source: {source_cfg.source}")

    def _resolve_bbox(self, source_cfg) -> tuple | None:
        """Get bbox from mask or project extent."""
        if source_cfg.mask_path:
            from hydromodpy.data_managers.common.geo_helpers import load_mask_geometry, geometry_to_bbox
            geom = load_mask_geometry(source_cfg.mask_path)
            return geometry_to_bbox(geom)
        if source_cfg.extent and self.project_extent:
            return self.project_extent
        return None

    def _apply_mask(self, records: list[PointRecord], source_cfg) -> list[PointRecord]:
        """Filter records by spatial mask if mask_path is set."""
        if not source_cfg.mask_path:
            return records
        from hydromodpy.data_managers.common.geo_helpers import load_mask_geometry, filter_locations_by_geometry
        geom = load_mask_geometry(source_cfg.mask_path)
        locs_to_check = [r.location for r in records if r.location is not None]
        inside = filter_locations_by_geometry(locs_to_check, geom)
        valid_ids = {loc.id for loc in inside}
        return [r for r in records if r.location is None or r.station_id in valid_ids]
