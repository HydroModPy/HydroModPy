"""DataStore: unified entry point for all data loading operations.

The DataStore is the main interface for loading data. It manages the catalog
(metadata registry backed by DuckDB) and delegates to variable-specific
managers.

If *workspace_root* is provided (path to an ``hmp init`` workspace), API
results are persisted as CSV files in ``data/<variable>/`` and registered
in ``data/cache.duckdb`` under the workspace root. Custom data stays at the
path specified by the user in the TOML.

If *workspace_root* is None, data is loaded in memory only (no persistence).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB


def _find_workspace_root(start_path: Path) -> Path | None:
    """Walk up from *start_path* looking for a workspace directory.

    Recognises ``data/cache.duckdb`` and legacy ``catalog.duckdb`` / ``catalog.db``.
    """
    current = start_path.resolve()
    if current.is_file():
        current = current.parent
    for _ in range(10):
        has_catalog = (
            (current / "data" / "cache.duckdb").exists()
            or (current / "catalog.duckdb").exists()
            or (current / "catalog.db").exists()
        )
        if has_catalog and (current / "data").is_dir():
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
        If provided, ``data/cache.duckdb`` is opened at this location and API
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
            self.catalog = DataCatalogDuckDB(self.workspace_root / "data" / "cache.duckdb")
        else:
            self.workspace_root = None
            self.catalog = DataCatalogDuckDB()  # in-memory

        self.project_extent = project_extent
        self.project_period = project_period

    def _data_dir(self, variable_name: str) -> Path | None:
        """Return ``workspace_root/data/<variable>/`` or None."""
        if self.workspace_root is None:
            return None
        d = self.workspace_root / "data" / variable_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    # Registry: variable_name → (module_path, class_name)
    _MANAGER_REGISTRY: dict[str, tuple[str, str]] = {
        "dem": ("hydromodpy.data.variables.dem.manager", "DemManager"),
        "geology": ("hydromodpy.data.variables.geology.manager", "GeologyManager"),
        "hydrography": ("hydromodpy.data.variables.hydrography.manager", "HydrographyManager"),
        "oceanic": ("hydromodpy.data.variables.oceanic.manager", "OceanicManager"),
        "hydrometry": ("hydromodpy.data.variables.hydrometry.manager", "HydrometryManager"),
        "piezometry": ("hydromodpy.data.variables.piezometry.manager", "PiezometryManager"),
        "water_quality": ("hydromodpy.data.variables.water_quality.manager", "WaterQualityManager"),
        "intermittency": ("hydromodpy.data.variables.intermittency.manager", "IntermittencyManager"),
        "recharge": ("hydromodpy.data.variables.recharge.manager", "RechargeManager"),
        "runoff": ("hydromodpy.data.variables.runoff.manager", "RunoffManager"),
        "precipitation": ("hydromodpy.data.variables.precipitation.manager", "PrecipitationManager"),
        "etp": ("hydromodpy.data.variables.etp.manager", "EtpManager"),
        "temperature": ("hydromodpy.data.variables.temperature.manager", "TemperatureManager"),
        "wind": ("hydromodpy.data.variables.wind.manager", "WindManager"),
        "humidity": ("hydromodpy.data.variables.humidity.manager", "HumidityManager"),
        "radiation": ("hydromodpy.data.variables.radiation.manager", "RadiationManager"),
        "soil_moisture": ("hydromodpy.data.variables.soil_moisture.manager", "SoilMoistureManager"),
    }

    def _load_variable(self, variable_name: str, config, **extra_kwargs) -> LoadResult:
        """Instantiate the right manager and load data."""
        import importlib
        entry = self._MANAGER_REGISTRY.get(variable_name)
        if entry is None:
            raise ValueError(f"Unknown variable: {variable_name}")
        module_path, class_name = entry
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        mgr = cls(
            config=config, catalog=self.catalog,
            project_extent=self.project_extent,
            project_period=self.project_period,
            data_dir=self._data_dir(variable_name),
            **extra_kwargs,
        )
        return mgr.load()

    def load_hydrography(self, config, *, geographic, out_path):
        """Load hydrography data (vector or raster) with catalog caching."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager
        mgr = HydrographyManager(
            config=config, geographic=geographic, out_path=out_path,
            catalog=self.catalog, data_dir=self._data_dir("hydrography"),
        )
        return mgr.load()

    def load_hydrometry(self, config) -> LoadResult:
        return self._load_variable("hydrometry", config)

    def load_piezometry(self, config) -> LoadResult:
        return self._load_variable("piezometry", config)

    def load_water_quality(self, config) -> LoadResult:
        return self._load_variable("water_quality", config)

    def load_intermittency(self, config) -> LoadResult:
        return self._load_variable("intermittency", config)

    def load_recharge(self, config) -> LoadResult:
        return self._load_variable("recharge", config)

    def load_runoff(self, config) -> LoadResult:
        return self._load_variable("runoff", config)

    def load_precipitation(self, config) -> LoadResult:
        return self._load_variable("precipitation", config)

    def load_etp(self, config) -> LoadResult:
        return self._load_variable("etp", config)

    def load_temperature(self, config) -> LoadResult:
        return self._load_variable("temperature", config)

    def load_wind(self, config) -> LoadResult:
        return self._load_variable("wind", config)

    def load_humidity(self, config) -> LoadResult:
        return self._load_variable("humidity", config)

    def load_radiation(self, config) -> LoadResult:
        return self._load_variable("radiation", config)

    def load_soil_moisture(self, config) -> LoadResult:
        return self._load_variable("soil_moisture", config)

    def cache_info(self, variable: str | None = None) -> pd.DataFrame:
        """Show catalog entries."""
        return self.catalog.list_entries(variable=variable)

    def get_completeness_report(
        self, records: LoadResult | list[PointRecord],
    ) -> pd.DataFrame:
        """Compute per-station completeness stats for point records."""
        from hydromodpy.data.common.validation import compute_completeness

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
