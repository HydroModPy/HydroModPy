"""Piezometry manager: orchestrates custom and API loading."""

from __future__ import annotations

from hydromodpy.data_managers.common.base_manager import BaseVariableManager
from hydromodpy.data_managers.contracts.timeseries import PointRecord
from hydromodpy.data_managers.variables.piezometry.config import PiezometryConfig, PiezometrySourceConfig


class PiezometryManager(BaseVariableManager):

    VARIABLE_NAME = "piezometry"
    INTERNAL_UNIT = "m"

    def _fetch_from_source(self, source_cfg: PiezometrySourceConfig) -> list[PointRecord]:
        if source_cfg.source == "custom":
            from hydromodpy.data_managers.variables.piezometry.custom import load_custom
            records = load_custom(
                source_cfg, project_period=self.project_period,
                internal_unit=self.INTERNAL_UNIT,
            )
            return self._apply_mask(records, source_cfg)
        elif source_cfg.source == "hubeau":
            return self._fetch_hubeau(source_cfg)
        raise ValueError(f"Unknown piezometry source: {source_cfg.source}")

    def _fetch_hubeau(self, source_cfg: PiezometrySourceConfig) -> list[PointRecord]:
        """Fetch from Hub'Eau with smart cache (partial coverage + merge)."""
        from hydromodpy.data_managers.variables.piezometry.apis.hubeau import fetch

        if self.project_period is None:
            raise ValueError("project_period required for Hub'Eau.")

        nearest_to = self._resolve_nearest_to(source_cfg) if source_cfg.nearest else None

        def _fetch_for(sids, start, end):
            return fetch(
                product=source_cfg.product, bbox=self._resolve_bbox(source_cfg),
                station_ids=sids, date_start=start, date_end=end,
                nearest_to=nearest_to,
                require_observations=source_cfg.require_observations,
                fallback_search_radius_km=source_cfg.fallback_search_radius_km,
            )

        # Try cache for explicitly requested station_ids
        if source_cfg.station_ids and not source_cfg.force_refresh:
            ready = []
            missing_ids = []
            to_persist = []
            for sid in source_cfg.station_ids:
                if self._is_empty_sentinel(source="hubeau", station_id=sid):
                    print(f"  Hub'Eau no-data (cached): {sid}")
                    continue
                rec = self._load_cached_api_record(source="hubeau", station_id=sid)
                if rec is not None:
                    gaps = self._compute_missing_periods(rec.date_start, rec.date_end)
                    if not gaps:
                        ready.append(rec)
                        print(f"  Hub'Eau cache hit: {sid}")
                    else:
                        parts = []
                        for gs, ge in gaps:
                            parts.extend(_fetch_for([sid], gs, ge))
                        if parts:
                            merged = self._merge_into_record(rec, *parts)
                            ready.append(merged)
                            to_persist.append(merged)
                            print(f"  Hub'Eau cache merge: {sid} (+{len(gaps)} period(s))")
                        else:
                            ready.append(rec)
                else:
                    missing_ids.append(sid)

            if to_persist:
                self._persist_api_records(to_persist, "hubeau")
            if not missing_ids:
                return self._apply_mask(ready, source_cfg)

            records = _fetch_for(
                missing_ids, self.project_period[0], self.project_period[1],
            )
            self._persist_api_records(records, "hubeau")
            fetched_ids = {r.station_id for r in records}
            empty_ids = [s for s in missing_ids if s not in fetched_ids]
            if empty_ids:
                self._register_empty_api_stations(empty_ids, "hubeau")
            return self._apply_mask(ready + records, source_cfg)

        # No cache for bbox-based discovery — always discover, then persist
        records = _fetch_for(
            source_cfg.station_ids,
            self.project_period[0], self.project_period[1],
        )
        self._persist_api_records(records, "hubeau")
        return self._apply_mask(records, source_cfg)

    def _resolve_nearest_to(self, source_cfg) -> tuple[float, float] | None:
        """Compute centroid of the project extent for nearest-piezometer search."""
        bbox = self._resolve_bbox(source_cfg)
        if bbox is None and self.project_extent is not None:
            bbox = self.project_extent
        if bbox is None:
            return None
        xmin, ymin, xmax, ymax = bbox
        return ((xmin + xmax) / 2, (ymin + ymax) / 2)

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
