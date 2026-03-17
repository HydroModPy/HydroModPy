"""DataStore: unified entry point for all data loading operations.

The DataStore is the main interface for loading data. It manages the catalog
(metadata registry) and delegates to variable-specific managers.

If *workspace_root* is provided (path to an ``hmp init`` workspace), API
results are persisted as CSV files in ``data/<variable>/`` and registered
in ``catalog.db`` at the workspace root. Custom data stays at the path
specified by the user in the TOML.

If *workspace_root* is None, data is loaded in memory only (no persistence).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from hydromodpy.data_managers.contracts.load_result import LoadResult
from hydromodpy.data_managers.contracts.timeseries import PointRecord
from hydromodpy.data_managers.registry.catalog import DataCatalog


def _find_workspace_root(start_path: Path) -> Path | None:
    """Walk up from *start_path* looking for a directory containing ``catalog.db``
    and ``data/``.  Returns the workspace root or None."""
    current = start_path.resolve()
    if current.is_file():
        current = current.parent
    for _ in range(10):  # limit depth
        if (current / "catalog.db").exists() and (current / "data").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


class DataStore:
    """Central coordinator for data loading, caching, and project clipping.

    Parameters
    ----------
    workspace_root : Path or str, optional
        Root of the HydroModPy workspace (created by ``hmp init``).
        If provided, ``catalog.db`` is opened at this location and API
        results are saved as CSV in ``data/<variable>/``.
        If *None*, the catalog is in-memory and nothing is persisted.
    project_extent : tuple, optional
        Bounding box (xmin, ymin, xmax, ymax) for spatial filtering.
    project_period : tuple[datetime, datetime], optional
        (start, end) for temporal filtering.
    """

    def __init__(
        self,
        *,
        workspace_root: str | Path | None = None,
        project_extent: tuple | None = None,
        project_period: tuple[datetime, datetime] | None = None,
    ):
        if workspace_root is not None:
            self.workspace_root = Path(workspace_root).expanduser().resolve()
            if not (self.workspace_root / "data").is_dir():
                raise FileNotFoundError(
                    f"Workspace invalide : dossier 'data/' introuvable dans "
                    f"{self.workspace_root}. Lancez 'hmp init' ou verifiez le chemin."
                )
            self.catalog = DataCatalog(self.workspace_root / "catalog.db")
        else:
            self.workspace_root = None
            self.catalog = DataCatalog()  # in-memory

        self.project_extent = project_extent
        self.project_period = project_period

    def _data_dir(self, variable_name: str) -> Path | None:
        """Return ``workspace_root/data/<variable>/`` or None."""
        if self.workspace_root is None:
            return None
        d = self.workspace_root / "data" / variable_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_hydrography(self, config, *, geographic, out_path):
        """Load hydrography data (vector or raster) with catalog caching."""
        from hydromodpy.data_managers.variables.hydrography.manager import HydrographyManager
        mgr = HydrographyManager(
            config=config, geographic=geographic, out_path=out_path,
            catalog=self.catalog, data_dir=self._data_dir("hydrography"),
        )
        return mgr.load()

    def load_intermittency(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.intermittency.manager import IntermittencyManager
        mgr = IntermittencyManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("intermittency"),
        )
        return mgr.load()

    def load_hydrometry(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.hydrometry.manager import HydrometryManager
        mgr = HydrometryManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("hydrometry"),
        )
        return mgr.load()

    def load_piezometry(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.piezometry.manager import PiezometryManager
        mgr = PiezometryManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("piezometry"),
        )
        return mgr.load()

    def load_water_quality(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.water_quality.manager import WaterQualityManager
        mgr = WaterQualityManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("water_quality"),
        )
        return mgr.load()

    def load_recharge(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.recharge.manager import RechargeManager
        mgr = RechargeManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("recharge"),
        )
        return mgr.load()

    def load_runoff(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.runoff.manager import RunoffManager
        mgr = RunoffManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("runoff"),
        )
        return mgr.load()

    def load_precipitation(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.precipitation.manager import PrecipitationManager
        mgr = PrecipitationManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("precipitation"),
        )
        return mgr.load()

    def load_etp(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.etp.manager import EtpManager
        mgr = EtpManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("etp"),
        )
        return mgr.load()

    def load_temperature(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.temperature.manager import TemperatureManager
        mgr = TemperatureManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("temperature"),
        )
        return mgr.load()

    def load_wind(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.wind.manager import WindManager
        mgr = WindManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("wind"),
        )
        return mgr.load()

    def load_humidity(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.humidity.manager import HumidityManager
        mgr = HumidityManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("humidity"),
        )
        return mgr.load()

    def load_radiation(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.radiation.manager import RadiationManager
        mgr = RadiationManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("radiation"),
        )
        return mgr.load()

    def load_soil_moisture(self, config) -> LoadResult:
        from hydromodpy.data_managers.variables.soil_moisture.manager import SoilMoistureManager
        mgr = SoilMoistureManager(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir("soil_moisture"),
        )
        return mgr.load()

    def cache_info(self, variable: str | None = None) -> pd.DataFrame:
        """Show catalog entries."""
        return self.catalog.list_entries(variable=variable)

    def get_completeness_report(
        self, records: LoadResult | list[PointRecord],
    ) -> pd.DataFrame:
        """Compute per-station completeness stats for point records."""
        from hydromodpy.data_managers.common.validation import compute_completeness

        if isinstance(records, LoadResult):
            records = records.points

        start = self.project_period[0] if self.project_period else None
        end = self.project_period[1] if self.project_period else None

        rows = []
        for rec in records:
            stats = compute_completeness(
                rec.data, station_id=rec.station_id,
                start_date=start or rec.date_start,
                end_date=end or rec.date_end,
            )
            stats["variable"] = rec.variable
            stats["source"] = rec.source
            stats["is_constant"] = rec.is_constant
            rows.append(stats)

        return pd.DataFrame(rows)

    def cleanup(self) -> int:
        """Remove catalog entries whose files no longer exist on disk."""
        return self.catalog.cleanup()

    def clear_cache(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        delete_files: bool = False,
    ) -> int:
        """Remove catalog entries (and optionally their files)."""
        return self.catalog.invalidate(
            variable=variable, source=source, delete_files=delete_files,
        )
