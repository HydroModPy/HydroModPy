"""Post-hoc data reader for the display package.

This module discovers and loads simulation outputs without requiring
runtime objects.  ``GeographicArtifacts`` reads geographic rasters from
the ``SimulationCatalog`` (preferred) or falls back to files on disk.

Typical usage::

    ctx = PosthocContext.from_toml("path/to/project.toml")
    for run in ctx.runs:
        print(run.run_id, run.watertable_depth_rasters)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeographicArtifacts:
    """Geographic data for display — reads from catalog or files.

    Use :meth:`from_catalog` when a ``SimulationCatalog`` is available (preferred).
    Use :meth:`discover` as fallback when only the filesystem is available.
    """

    geographic_dir: Path | None = None
    correcflow_dir: Path | None = None
    watershed_shp: Path | None = None
    watershed_dem: Path | None = None
    watershed_box_buff_dem: Path | None = None
    watershed_contour_shp: Path | None = None
    river_network_shp: Path | None = None
    dem_acc_tif: Path | None = None

    # Catalog reference (None when using file-based discovery)
    _store: Any = field(default=None, repr=False, compare=False)
    _sim_id: str | None = field(default=None, repr=False, compare=False)
    _project: str | None = field(default=None, repr=False, compare=False)

    def read_raster(self, name: str) -> tuple[np.ndarray, dict]:
        """Read a geographic raster as (data, metadata) from the catalog.

        Rasters are stored per-simulation in the Zarr archive under the
        ``geographic/`` group.  Access goes through
        ``catalog.open_zarr(sim_id).read_geographic_raster(name)``.

        Parameters
        ----------
        name : str
            Raster name, e.g. ``"watershed_dem"``, ``"watershed_box_buff_dem"``.

        Returns
        -------
        (np.ndarray, dict)
            Data array and metadata dict with ``transform``, ``crs``, ``nodata``.

        Raises
        ------
        KeyError
            If the raster is not found in the catalog.
        """
        if self._store is None or self._sim_id is None:
            raise KeyError(
                f"Geographic raster '{name}' unavailable: no catalog/sim_id attached. "
                "Use GeographicArtifacts.from_catalog(catalog, sim_id, project) first."
            )
        zarr = self._store.open_zarr(self._sim_id)
        return zarr.read_geographic_raster(name)

    def read_feature(self, name: str):
        """Read a vector feature from the catalog as a GeoDataFrame.

        Features are stored per-project in the DuckDB catalog.

        Parameters
        ----------
        name : str
            Feature name, e.g. ``"watershed"``, ``"river_network"``.
        """
        if self._store is None or self._project is None:
            raise KeyError(f"Feature '{name}' unavailable: no catalog/project attached.")
        return self._store.read_geographic_feature(self._project, name)

    def feature_path(self, name: str, output_dir: Path | str) -> Path:
        """Materialize a vector feature to a temp shapefile.

        Needed by downstream plotting functions that expect file paths.
        The file is written to *output_dir* and should be cleaned up by
        the caller (e.g. via ``tempfile.TemporaryDirectory``).
        """
        gdf = self.read_feature(name)
        out = Path(output_dir) / f"{name}.shp"
        gdf.to_file(str(out))
        return out

    @classmethod
    def from_catalog(
        cls,
        catalog: Any,
        sim_id: str,
        project: str,
    ) -> GeographicArtifacts:
        """Build artifacts backed by a SimulationCatalog (no filesystem needed)."""
        return cls(_store=catalog, _sim_id=sim_id, _project=project)

    @classmethod
    def from_store(cls, store: Any, sim_id: str = "", project: str = "") -> GeographicArtifacts:
        """Backward-compatible alias for :meth:`from_catalog`."""
        return cls(_store=store, _sim_id=sim_id or None, _project=project or None)

    @classmethod
    def discover(cls, geographic_dir: Path) -> GeographicArtifacts:
        """Scan a geographic directory and return found artifacts."""
        stable_dir = geographic_dir.parent if geographic_dir.is_dir() else None
        correcflow_dir = stable_dir / "demcorrecflow" if stable_dir else None

        if not geographic_dir.is_dir():
            return cls(geographic_dir=geographic_dir, correcflow_dir=correcflow_dir)

        def _find(name: str, ext: str) -> Path | None:
            p = geographic_dir / f"{name}.{ext}"
            return p if p.exists() else None

        river_shp = _find("river_network", "shp")

        dem_acc: Path | None = None
        if correcflow_dir is not None:
            p = correcflow_dir / "dem_acc.tif"
            if p.exists():
                dem_acc = p

        return cls(
            geographic_dir=geographic_dir,
            correcflow_dir=correcflow_dir,
            watershed_shp=_find("watershed", "shp"),
            watershed_dem=_find("watershed_dem", "tif"),
            watershed_box_buff_dem=_find("watershed_box_buff_dem", "tif"),
            watershed_contour_shp=_find("watershed_contour", "shp"),
            river_network_shp=river_shp,
            dem_acc_tif=dem_acc,
        )


@dataclass(frozen=True)
class RunArtifacts:
    """Lightweight descriptor for one simulation run.

    All data is read from the ``SimulationCatalog`` (DuckDB + Zarr).
    Filesystem paths are derived lazily from ``run_dir`` for legacy
    compatibility (posthoc orchestration, native mesh figures, particles).
    """

    run_id: str
    run_dir: Path | None = None

    @property
    def postprocess_dir(self) -> Path | None:
        if self.run_dir is None:
            return None
        p = self.run_dir / "_postprocess"
        return p if p.is_dir() else None

    @property
    def native_mesh_figure_dir(self) -> Path | None:
        if self.run_dir is None:
            return None
        p = self.run_dir / "_postprocess" / "_figures" / "native_mesh"
        return p if p.is_dir() else None

    @property
    def simulated_timeseries_csv(self) -> Path | None:
        if self.run_dir is None:
            return None
        p = self.run_dir / "_postprocess" / "_timeseries" / "_simulated_timeseries.csv"
        return p if p.exists() else None

    @property
    def pathlines_weighted_shp(self) -> Path | None:
        if self.run_dir is None:
            return None
        p = self.run_dir / "_postprocess" / "_particles" / "pathlines_weighted.shp"
        return p if p.exists() else None

    @property
    def starting_weighted_shp(self) -> Path | None:
        if self.run_dir is None:
            return None
        p = self.run_dir / "_postprocess" / "_particles" / "starting_weighted.shp"
        return p if p.exists() else None

    @classmethod
    def discover(cls, run_dir: Path) -> RunArtifacts:
        """Create a run artifact from a directory name."""
        return cls(run_id=run_dir.name, run_dir=run_dir)

    def base_raster(self, geographic: GeographicArtifacts) -> Path | None:
        """Return the best available base raster for map overlays.

        Checks for a solver grid template on disk first, then falls back
        to the geographic watershed DEM path.
        """
        if self.run_dir is not None:
            solver_tpl = self.run_dir / "_solver_grid_template.tif"
            if solver_tpl.exists():
                return solver_tpl
        return geographic.watershed_dem


@dataclass(frozen=True)
class PosthocContext:
    """Complete post-hoc context for one project."""

    project_dir: Path
    geographic: GeographicArtifacts
    runs: list[RunArtifacts]

    @classmethod
    def from_project_dir(cls, project_dir: Path) -> PosthocContext:
        """Build a context by scanning output directories.

        Checks ``.solver_scratch/`` first, then falls back to
        ``results_simulations/`` for legacy layouts.
        """
        project_dir = Path(project_dir).resolve()

        from hydromodpy.core.workspace.path_registry import LEGACY_STABLE_DIR
        geo_dir = project_dir / LEGACY_STABLE_DIR / "geographic"
        geographic = GeographicArtifacts.discover(geo_dir)

        runs: list[RunArtifacts] = []
        for folder_name in (".solver_scratch", "results_simulations"):
            sims_dir = project_dir / folder_name
            if not sims_dir.is_dir():
                continue
            for run_dir in sorted(sims_dir.iterdir()):
                if run_dir.is_dir() and not run_dir.name.startswith("_"):
                    pp = run_dir / "_postprocess"
                    if pp.is_dir():
                        runs.append(RunArtifacts.discover(run_dir))

        return cls(
            project_dir=project_dir,
            geographic=geographic,
            runs=runs,
        )

    @classmethod
    def from_toml(cls, toml_path: str | Path) -> PosthocContext:
        """Build a context from a project TOML file path.

        The project directory is assumed to be the parent of the TOML file.
        """
        toml_path = Path(toml_path).resolve()
        return cls.from_project_dir(toml_path.parent)

    @classmethod
    def from_catalog(
        cls,
        project_dir: Path,
        catalog,
        sim_id: str,
        project: str,
    ) -> PosthocContext:
        """Build a context from a SimulationCatalog (preferred, no filesystem needed).

        Geographic rasters are read from the sim's Zarr archive.  Vector
        features are read from DuckDB keyed by *project*.  Run artifacts
        (particles, solver grid template) are still discovered on disk when
        available.

        Parameters
        ----------
        project_dir : Path
            Project root directory.
        catalog : SimulationCatalog
            An open SimulationCatalog instance.
        sim_id : str
            Simulation UUID whose Zarr holds geographic rasters.
        project : str
            Project name used to look up features in DuckDB.
        """
        project_dir = Path(project_dir).resolve()

        geographic = GeographicArtifacts.from_catalog(catalog, sim_id, project)

        # Discover run artifacts from solver scratch / results_simulations.
        runs: list[RunArtifacts] = []
        for folder_name in (".solver_scratch", "results_simulations"):
            sims_dir = project_dir / folder_name
            if not sims_dir.is_dir():
                continue
            for run_dir in sorted(sims_dir.iterdir()):
                if run_dir.is_dir() and not run_dir.name.startswith("_"):
                    runs.append(RunArtifacts.discover(run_dir))

        return cls(
            project_dir=project_dir,
            geographic=geographic,
            runs=runs,
        )

    @classmethod
    def from_result_store(
        cls,
        project_dir: Path,
        store,
        sim_id: str = "",
        project: str = "",
    ) -> PosthocContext:
        """Backward-compatible alias for :meth:`from_catalog`."""
        return cls.from_catalog(
            project_dir, store,
            sim_id=sim_id, project=project,
        )
