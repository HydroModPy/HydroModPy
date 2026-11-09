"""DataStore: unified entry point for all data loading operations.

The store holds the data cache of one data folder, a
:class:`~hydromodpy.data.provenance.sidecars.CacheIndex` read from the sidecars
next to the files, and hands it to each variable it loads.

With a workspace root (an ``hmp workspace init`` workspace) or a data root,
what a variable fetches is written as files in ``data/<variable>/``, each with
its sidecar. A file the user declares stays where the TOML names it and is no
row of the cache. Without either, nothing is written: the index is empty, finds
nothing and refuses a write.

Two cases of a ``[sites]`` launch share one data folder. Each writes its files
and sidecars in place, one station chronicle at a time under its file lock.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from hydromodpy.core.runtime.bounds import Bounds
from hydromodpy.data.contracts.load_result import LoadResult
from hydromodpy.data.contracts.timeseries import PointRecord
from hydromodpy.data.loading._dispatch import variable_class_for
from hydromodpy.data.provenance.sidecars import CacheIndex


class DataStore:
    """Central coordinator for data loading, caching, and project clipping.

    Parameters
    ----------
    workspace_root : Path or str, optional
        Root of the HydroModPy workspace (created by ``hmp workspace init``).
        If provided, its ``data/`` folder holds the cache.
    data_root : Path or str, optional
        The data folder itself, which wins over *workspace_root*. Without
        either, nothing is persisted.
    index : CacheIndex, optional
        An index already read, shared with another store of the same folder.
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
        index: CacheIndex | None = None,
        project_extent: tuple | None = None,
        project_period: tuple[datetime, datetime] | None = None,
        bounds: Bounds | None = None,
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
                    f"Not a workspace: the folder 'data/' is not in {self.workspace_root}. "
                    "Run 'hmp workspace init', or check the path."
                )
            self.data_root = self.workspace_root / "data"
        else:
            self.workspace_root = None
            self.data_root = None

        self.index = index if index is not None else CacheIndex(self.data_root)

        self.project_extent = project_extent
        self.project_period = project_period
        # The bounds of the call this store serves: every variable it builds
        # puts them into each request, so the fetcher refuses a host the
        # caller did not allow. ``None`` keeps the all-allowing default.
        self.bounds = bounds if bounds is not None else Bounds()

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
    ) -> LoadResult:
        """Build the variable and load its data.

        Every variable on this path takes the same five arguments and no
        others. The escape hatch that used to sit here, ``**extra_kwargs``,
        existed for one caller and one key -- ``geographic`` for oceanic --
        and removing it is what makes "a variable receives no project-scoped
        object" a property of the path rather than a habit of its callers.
        """
        cls = variable_class_for(variable_name)
        variable = cls(
            config=config,
            index=self.index,
            project_extent=self.project_extent if project_extent is None else project_extent,
            project_period=self.project_period if project_period is None else project_period,
            data_dir=self._data_dir(variable_name),
        )
        variable.bounds = self.bounds
        result = variable.load()
        if export_dir is not None:
            variable.export(result, Path(export_dir))
        return result

    def load_dem(
        self,
        config: Any,
        *,
        project_extent: tuple | None = None,
    ) -> LoadResult:
        """Load DEM data.

        The extent comes from the source config alone -- ``mask_path``, which
        the runtime loader fills in from the delineated watershed, or
        ``extent`` together with ``project_extent``. There is no
        ``geographic`` parameter: see
        :mod:`hydromodpy.data.common.source_extent`.
        """
        from hydromodpy.data.variables.dem.variable import DemVariable

        variable = DemVariable(
            config=config,
            index=self.index,
            project_extent=self.project_extent if project_extent is None else project_extent,
            data_dir=self._data_dir("dem"),
        )
        variable.bounds = self.bounds
        return variable.load()

    def load_geology(
        self,
        config: Any,
        *,
        project_extent: tuple | None = None,
    ) -> LoadResult:
        """Load geology data, on the same extent contract as :meth:`load_dem`."""
        from hydromodpy.data.variables.geology.variable import GeologyVariable

        variable = GeologyVariable(
            config=config,
            index=self.index,
            project_extent=self.project_extent if project_extent is None else project_extent,
            data_dir=self._data_dir("geology"),
        )
        variable.bounds = self.bounds
        return variable.load()

    def fetch_network(
        self, source_cfg: Any, mask_path: str | Path, *, bounds: Bounds | None = None
    ) -> Any:
        """Return the network one listed source answers over the box of *mask_path*.

        Read from this store's cache and stored in it, as a run stores it: a
        workspace store keeps the answer under ``data/hydrography/``.
        *bounds* is the :class:`Bounds` of the call that asked for the
        network; unset, the bounds of this store. The source is built under
        them, so a host they do not allow is refused before anything connects.
        """
        from hydromodpy.data.families.common import source_within_bounds
        from hydromodpy.data.variables.hydrography.api_source import source_from_section
        from hydromodpy.data.variables.hydrography.variable import fetch_network_through_cache

        call_bounds = self.bounds if bounds is None else bounds
        source = source_within_bounds(source_from_section(source_cfg), call_bounds)
        return fetch_network_through_cache(
            source_cfg,
            Path(mask_path),
            index=self.index,
            data_dir=self._data_dir("hydrography"),
            source=source,
        )

    def load_hydrography(
        self,
        config: Any,
        *,
        out_path: str | Path,
        base_raster: str | Path | None = None,
        stable_folder: str | Path | None = None,
    ) -> LoadResult:
        """Load hydrography data (vector or raster) through the data cache.

        The extent is ``config.mask_path``; ``base_raster`` is only the grid the
        clipped network is rasterized onto.
        """
        from hydromodpy.data.variables.hydrography.variable import HydrographyVariable

        variable = HydrographyVariable(
            config=config,
            out_path=out_path,
            base_raster=base_raster,
            index=self.index,
            data_dir=self._data_dir("hydrography"),
            stable_folder=stable_folder,
        )
        variable.bounds = self.bounds
        return variable.load()

    def load_oceanic(
        self,
        config: Any,
        *,
        project_extent: tuple | None = None,
        project_period: tuple[datetime, datetime] | None = None,
    ) -> LoadResult:
        return self.load_variable(
            "oceanic",
            config,
            project_extent=project_extent,
            project_period=project_period,
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
        """Return the rows of the data cache, one line each."""
        return pd.DataFrame([row.to_dict() for row in self.index.rows(variable=variable)])

    def get_completeness_report(
        self,
        records: LoadResult | list[PointRecord],
    ) -> pd.DataFrame:
        """Compute per-station completeness stats for point records."""
        from hydromodpy.data.contracts.completeness import compute_completeness

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
        """Remove the sidecars whose files no longer exist on disk. Returns the count."""
        return len(self.index.forget_orphans())

    def clear_cache(
        self,
        *,
        variable: str | None = None,
        source: str | None = None,
        delete_files: bool = False,
    ) -> int:
        """Remove the rows that match, and their files with *delete_files*. Returns the count."""
        rows = self.index.rows(variable=variable, source=source)
        for row in rows:
            self.index.forget(row, delete_file=delete_files)
        return len(rows)
