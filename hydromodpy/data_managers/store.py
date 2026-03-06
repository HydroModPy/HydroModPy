"""DataStore: unified entry point for all data loading operations."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from hydromodpy.data_managers.contracts.timeseries import PointRecord
from hydromodpy.data_managers.registry.catalog import DataCatalog


class DataStore:
    """Central coordinator for data loading, caching, and project clipping."""

    def __init__(
        self,
        *,
        data_dir: str | Path,
        project_data_dir: str | Path | None = None,
        project_extent: tuple | None = None,
        project_period: tuple[datetime, datetime] | None = None,
    ):
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.project_data_dir = Path(project_data_dir).resolve() if project_data_dir else None
        if self.project_data_dir:
            self.project_data_dir.mkdir(parents=True, exist_ok=True)

        self.project_extent = project_extent
        self.project_period = project_period
        self.catalog = DataCatalog(self.data_dir / "catalog.db")

    def load_hydrometry(self, config) -> list[PointRecord]:
        from hydromodpy.data_managers.hydrometry.manager import HydrometryManager
        mgr = HydrometryManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
        )
        return mgr.load()

    def load_piezometry(self, config) -> list[PointRecord]:
        from hydromodpy.data_managers.piezometry.manager import PiezometryManager
        mgr = PiezometryManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
        )
        return mgr.load()

    def load_water_quality(self, config) -> list[PointRecord]:
        from hydromodpy.data_managers.water_quality.manager import WaterQualityManager
        mgr = WaterQualityManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
        )
        return mgr.load()

    def cache_info(self, variable: str | None = None) -> pd.DataFrame:
        return self.catalog.list_entries(variable=variable)

    def clear_cache(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        delete_files: bool = False,
    ) -> int:
        return self.catalog.invalidate(
            variable=variable, source=source, delete_files=delete_files,
        )
