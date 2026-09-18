"""Oceanic manager: orchestrates custom, SHOM API, and constant loading.

Which gauge SHOM is asked for
-----------------------------
The manager used to hold a ``geographic`` object and hand it whole to
``apis/shom.py``, which read ``centroid_long_lat`` off it. The object is gone
and the selector is declared:

- ``station_ids`` names the gauges outright, and nothing spatial is needed;
- otherwise the extent -- ``mask_path``, which a project run fills in from the
  delineated watershed like every other timeseries source -- gives the point
  whose nearest gauge is read, taken as the centre of that extent in WGS84.

**Precedence, and not D116's refusal, and the difference is who put the second
selector there.** D116 refuses two selectors on a *request*, where both come
from the caller. Here the mask does not: ``_apply_default_masks`` fills
``mask_path`` on every source whose model declares the field, so a source that
names nothing but ``station_ids`` arrives at this manager carrying a watershed
it never asked for. Refusing that pair makes ``station_ids`` unusable on every
project run -- measured, and it is what the first version of this phase did.
The named station is the specific answer and wins, the way ``mask_path`` wins
over ``extent`` inside :func:`resolve_source_extent` itself. Naming neither is
still a refusal.
"""

from __future__ import annotations

from datetime import datetime

from hydromodpy.data.common.source_extent import resolve_source_extent
from hydromodpy.data.managers.base_manager_field import BaseFieldManager
from hydromodpy.data.variables.oceanic.config import OceanicSourceConfig


class OceanicManager(BaseFieldManager):
    """Multi-source oceanic manager.

    Combines constant MSL, custom CSV/NC/TIF data, and SHOM tide gauge API.
    """

    VARIABLE_NAME = "oceanic"
    INTERNAL_UNIT = "m"

    def _fetch_from_source(self, source_cfg: OceanicSourceConfig):
        if source_cfg.source == "custom":
            from hydromodpy.data.variables.oceanic.custom import load_custom

            records = load_custom(
                source_cfg,
                project_period=self.project_period,
                internal_unit=self.INTERNAL_UNIT,
            )
            return self._handle_custom_results(records, source_cfg)
        elif source_cfg.source == "shom":
            return self._fetch_shom(source_cfg)
        elif source_cfg.source == "constant":
            from hydromodpy.data.variables.oceanic.constant import generate_constant

            return generate_constant(source_cfg, project_period=self.project_period)
        raise ValueError(f"Unknown oceanic source: {source_cfg.source}")

    def _fetch_shom(self, source_cfg: OceanicSourceConfig):
        from hydromodpy.data.variables.oceanic.apis.shom import fetch

        start, end = self._resolve_shom_dates()
        station_ids = list(source_cfg.station_ids or ())

        if station_ids:
            records = []
            for station_id in station_ids:
                records.extend(
                    fetch(
                        date_start=start,
                        date_end=end,
                        station_id=station_id,
                        cache_dir=self.data_dir,
                    )
                )
            return records

        extent = resolve_source_extent(source_cfg, project_extent=self.project_extent)
        if extent is None:
            raise ValueError(
                "A SHOM source needs one selector: station_ids, or mask_path (a project "
                "run fills it in from the delineated watershed)."
            )

        lonlat = extent.to_crs("EPSG:4326")
        return fetch(
            date_start=start,
            date_end=end,
            near_lat=(lonlat.ymin + lonlat.ymax) / 2.0,
            near_lon=(lonlat.xmin + lonlat.xmax) / 2.0,
            fallback_search_radius_km=source_cfg.fallback_search_radius_km,
            cache_dir=self.data_dir,
        )

    def _resolve_shom_dates(self) -> tuple[datetime, datetime]:
        """Resolve SHOM download date range from config or project period."""
        if self.project_period is not None:
            return self.project_period
        cfg = self.config
        if cfg.date_start and cfg.date_end:
            return (
                datetime.fromisoformat(cfg.date_start),
                datetime.fromisoformat(cfg.date_end),
            )
        raise ValueError(
            "SHOM source requires date_start/date_end in oceanic config or a project_period."
        )
