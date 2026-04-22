"""Oceanic manager: orchestrates custom, SHOM API, and constant loading."""

from __future__ import annotations

from datetime import datetime

from hydromodpy.data.base_manager import BaseFieldManager
from hydromodpy.data.variables.oceanic.config import OceanicConfig, OceanicSourceConfig


class OceanicManager(BaseFieldManager):
    """Multi-source oceanic manager.

    Combines constant MSL, custom CSV/NC/TIF data, and SHOM tide gauge API.
    Accepts an extra *geographic* parameter needed by the SHOM source.
    """

    VARIABLE_NAME = "oceanic"
    INTERNAL_UNIT = "m"

    def __init__(
        self,
        *,
        config: OceanicConfig,
        catalog=None,
        project_period: tuple[datetime, datetime] | None = None,
        project_extent: tuple | None = None,
        geographic: object | None = None,
        data_dir: "Path | None" = None,
    ) -> None:
        super().__init__(
            config=config,
            catalog=catalog,
            project_period=project_period,
            project_extent=project_extent,
            data_dir=data_dir,
        )
        self._geographic = geographic

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

        if self._geographic is None:
            raise ValueError("SHOM source requires a geographic object (watershed centroid).")

        start, end = self._resolve_shom_dates()
        return fetch(
            geographic=self._geographic,
            date_start=start,
            date_end=end,
            nearest=source_cfg.nearest,
            fallback_search_radius_km=source_cfg.fallback_search_radius_km,
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
