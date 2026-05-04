"""DataStore: unified entry point for all data loading operations.

The DataStore is the main interface for loading data. It manages the catalog
(metadata registry backed by DuckDB) and delegates to variable-specific
managers.

If *workspace_root* is provided (path to an ``hmp init`` workspace), API
results are persisted as CSV files in ``data/<variable>/`` and registered
in ``data/cache.duckdb`` under the workspace root. Custom data stays at the
path specified by the user in the TOML.

If *workspace_root* is None, data is loaded in memory only (no persistence).
Runtime callers may pass an existing catalog and data root so the simulation
loader and interactive facade share the same manager instantiation path.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.data._dispatch import get_manager_class
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.registry.catalog_duckdb import DataCatalogDuckDB


def _find_workspace_root(start_path: Path) -> Path | None:
    """Walk up from *start_path* looking for a workspace directory.

    Recognises the canonical ``data/cache.duckdb`` layout.
    """
    current = start_path.resolve()
    if current.is_file():
        current = current.parent
    for _ in range(10):
        if (current / "data" / "cache.duckdb").exists() and (current / "data").is_dir():
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
        data_root: str | Path | None = None,
        catalog: DataCatalogDuckDB | None = None,
        project_extent: tuple | None = None,
        project_period: tuple[datetime, datetime] | None = None,
    ):
        if data_root is not None:
            self.data_root = Path(data_root).expanduser().resolve()
            self.data_root.mkdir(parents=True, exist_ok=True)
            self.workspace_root = (
                Path(workspace_root).expanduser().resolve()
                if workspace_root is not None
                else self.data_root.parent
            )
        elif workspace_root is not None:
            self.workspace_root = Path(workspace_root).expanduser().resolve()
            if not (self.workspace_root / "data").is_dir():
                raise FileNotFoundError(
                    f"Workspace invalide : dossier 'data/' introuvable dans "
                    f"{self.workspace_root}. Lancez 'hmp init' ou verifiez le chemin."
                )
            self.data_root = self.workspace_root / "data"
        else:
            self.workspace_root = None
            self.data_root = None

        if catalog is not None:
            self.catalog = catalog
        elif self.data_root is not None:
            self.catalog = DataCatalogDuckDB(self.data_root / "cache.duckdb")
        else:
            self.catalog = DataCatalogDuckDB()

        self.project_extent = project_extent
        self.project_period = project_period

    def _data_dir(self, variable_name: str) -> Path | None:
        """Return ``data/<variable>/`` or None."""
        if self.data_root is None:
            return None
        d = self.data_root / variable_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def load_variable(
        self,
        variable_name: str,
        config: Any,
        *,
        project_extent: tuple | None = None,
        project_period: tuple[datetime, datetime] | None = None,
        export_dir: str | Path | None = None,
        **extra_kwargs: Any,
    ) -> LoadResult:
        """Instantiate the right manager and load data."""
        cls = get_manager_class(variable_name)
        mgr = cls(
            config=config,
            catalog=self.catalog,
            project_extent=self.project_extent if project_extent is None else project_extent,
            project_period=self.project_period if project_period is None else project_period,
            data_dir=self._data_dir(variable_name),
            **extra_kwargs,
        )
        result = mgr.load()
        if export_dir is not None:
            mgr.export(result, Path(export_dir))
        return result

    def load_dem(
        self,
        config: Any,
        *,
        geographic: Any = None,
        project_extent: tuple | None = None,
    ) -> LoadResult:
        """Load DEM data."""
        from hydromodpy.data.variables.dem.manager import DemManager

        manager = DemManager(
            config=config,
            catalog=self.catalog,
            project_extent=self.project_extent if project_extent is None else project_extent,
            data_dir=self._data_dir("dem"),
            geographic=geographic,
        )
        return manager.load()

    def load_geology(
        self,
        config: Any,
        *,
        geographic: Any = None,
        project_extent: tuple | None = None,
    ) -> LoadResult:
        """Load geology data."""
        from hydromodpy.data.variables.geology.manager import GeologyManager

        manager = GeologyManager(
            config=config,
            catalog=self.catalog,
            project_extent=self.project_extent if project_extent is None else project_extent,
            data_dir=self._data_dir("geology"),
            geographic=geographic,
        )
        return manager.load()

    def load_hydrography(
        self,
        config: Any,
        *,
        geographic: Any,
        out_path: str | Path,
        stable_folder: str | Path | None = None,
    ) -> LoadResult:
        """Load hydrography data (vector or raster) with catalog caching."""
        from hydromodpy.data.variables.hydrography.manager import HydrographyManager

        manager = HydrographyManager(
            config=config,
            geographic=geographic,
            out_path=out_path,
            catalog=self.catalog,
            data_dir=self._data_dir("hydrography"),
            stable_folder=stable_folder,
        )
        return manager.load()

    def load_oceanic(
        self,
        config: Any,
        *,
        geographic: Any = None,
        project_extent: tuple | None = None,
        project_period: tuple[datetime, datetime] | None = None,
    ) -> LoadResult:
        return self.load_variable(
            "oceanic",
            config,
            project_extent=project_extent,
            project_period=project_period,
            geographic=geographic,
        )

    def load_hydrometry(self, config) -> LoadResult:
        return self.load_variable("hydrometry", config)

    def load_piezometry(self, config) -> LoadResult:
        return self.load_variable("piezometry", config)

    def load_water_quality(self, config) -> LoadResult:
        return self.load_variable("water_quality", config)

    def load_intermittency(self, config) -> LoadResult:
        return self.load_variable("intermittency", config)

    def load_recharge(self, config) -> LoadResult:
        return self.load_variable("recharge", config)

    def load_runoff(self, config) -> LoadResult:
        return self.load_variable("runoff", config)

    def load_precipitation(self, config) -> LoadResult:
        return self.load_variable("precipitation", config)

    def load_etp(self, config) -> LoadResult:
        return self.load_variable("etp", config)

    def load_temperature(self, config) -> LoadResult:
        return self.load_variable("temperature", config)

    def load_wind(self, config) -> LoadResult:
        return self.load_variable("wind", config)

    def load_humidity(self, config) -> LoadResult:
        return self.load_variable("humidity", config)

    def load_radiation(self, config) -> LoadResult:
        return self.load_variable("radiation", config)

    def load_soil_moisture(self, config) -> LoadResult:
        return self.load_variable("soil_moisture", config)

    def cache_info(self, variable: str | None = None) -> pd.DataFrame:
        """Show catalog entries."""
        return self.catalog.list_entries(variable=variable)

    def get_completeness_report(
        self,
        records: LoadResult | list[PointRecord],
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
                rec.data,
                station_id=rec.station_id,
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
            variable=variable,
            source=source,
            delete_files=delete_files,
        )
