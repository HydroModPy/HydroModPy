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
import warnings

import pandas as pd

from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.registry.constants import (
    SENTINEL_CUSTOM,
    SENTINEL_EMPTY,
)

_CATALOG_IMPORT_WARNING_SHOWN = False


class _FallbackDataCatalog:
    """Minimal in-memory catalog used when SQLAlchemy is unavailable.

    The fallback deliberately disables smart cache lookups but preserves the
    DataStore/DataManager call contract for lightweight unit tests and
    no-persistence local usage.
    """

    def __init__(self, *_args, **_kwargs) -> None:
        self._entries: list[dict[str, object]] = []
        self._next_id = 1

    def find_cached(self, **_kwargs):
        return None

    def register(self, **kwargs) -> int:
        entry_id = self._next_id
        self._next_id += 1

        record = dict(kwargs)
        bbox = record.pop("bbox", None)
        if bbox is not None:
            record["bbox_xmin"], record["bbox_ymin"], record["bbox_xmax"], record["bbox_ymax"] = bbox
        else:
            record["bbox_xmin"] = None
            record["bbox_ymin"] = None
            record["bbox_xmax"] = None
            record["bbox_ymax"] = None

        for key in ("date_start", "date_end"):
            value = record.get(key)
            if hasattr(value, "isoformat"):
                record[key] = value.isoformat()

        record["id"] = entry_id
        self._entries.append(record)
        return entry_id

    def subsume_entries(self, **_kwargs) -> int:
        return 0

    def list_entries(self, variable: str | None = None) -> pd.DataFrame:
        rows = self._entries
        if variable is not None:
            rows = [row for row in rows if row.get("variable") == variable]
        return pd.DataFrame(rows)

    def cleanup(self) -> int:
        return 0

    def invalidate(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        station_id: str | None = None,
        delete_files: bool = False,
    ) -> int:
        removed = 0
        kept: list[dict[str, object]] = []
        for row in self._entries:
            matches = True
            if variable is not None and row.get("variable") != variable:
                matches = False
            if source is not None and row.get("source") != source:
                matches = False
            if station_id is not None and row.get("station_id") != station_id:
                matches = False

            if not matches:
                kept.append(row)
                continue

            removed += 1
            if delete_files:
                file_path = row.get("file_path")
                if isinstance(file_path, str) and file_path not in {SENTINEL_CUSTOM, SENTINEL_EMPTY}:
                    try:
                        candidate = Path(file_path)
                        if candidate.exists():
                            candidate.unlink()
                    except OSError:
                        pass
        self._entries = kept
        return removed


def _build_data_catalog(*args, **kwargs):
    """Create the persisted catalog, or a lightweight fallback when optional SQL support is absent."""
    global _CATALOG_IMPORT_WARNING_SHOWN
    try:
        from hydromodpy.data.registry.catalog import DataCatalog
    except ModuleNotFoundError as exc:
        if exc.name != "sqlalchemy":
            raise
        if not _CATALOG_IMPORT_WARNING_SHOWN:
            warnings.warn(
                "sqlalchemy is not installed; DataStore is using an in-memory fallback catalog. "
                "Catalog persistence and smart cache lookups are disabled.",
                stacklevel=2,
            )
            _CATALOG_IMPORT_WARNING_SHOWN = True
        return _FallbackDataCatalog(*args, **kwargs)
    return DataCatalog(*args, **kwargs)


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
            self.catalog = _build_data_catalog(self.workspace_root / "catalog.db")
        else:
            self.workspace_root = None
            self.catalog = _build_data_catalog()  # in-memory

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
