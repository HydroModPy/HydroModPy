"""Post-hoc data reader for the display package.

This module discovers and loads simulation outputs without requiring
runtime objects.  ``GeographicArtifacts`` reads geographic rasters from
the ``ResultStore`` (preferred) or falls back to files on disk.

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
    """Geographic data for display — reads from store or files.

    Use :meth:`from_store` when a ``ResultStore`` is available (preferred).
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

    # Store reference (None when using file-based discovery)
    _store: Any = field(default=None, repr=False, compare=False)

    def read_raster(self, name: str) -> tuple[np.ndarray, dict]:
        """Read a geographic raster as (data, metadata) from the store.

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
            If the raster is not found in the store.
        """
        if self._store is None:
            raise KeyError(
                f"Geographic raster '{name}' unavailable: no store attached. "
                "Use GeographicArtifacts.from_store(store) or persist_geographic_to_store() first."
            )
        data = self._store.read_geographic_raster(name)
        meta = self._store.read_geographic_raster_metadata(name)
        return data, meta

    def read_feature(self, name: str):
        """Read a vector feature from the store as a GeoDataFrame.

        Parameters
        ----------
        name : str
            Feature name, e.g. ``"watershed"``, ``"river_network"``.
        """
        if self._store is None:
            raise KeyError(f"Feature '{name}' unavailable: no store attached.")
        return self._store.read_features(name)

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
    def from_store(cls, store: Any) -> GeographicArtifacts:
        """Build artifacts backed by a ResultStore (no filesystem needed)."""
        return cls(_store=store)

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

    All data is read from the ``ResultStore`` (DuckDB + Zarr).
    """

    run_id: str
    run_dir: Path | None = None

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
    def from_result_store(
        cls,
        project_dir: Path,
        store,
    ) -> PosthocContext:
        """Build a context from the ResultStore (preferred, no filesystem needed).

        Geographic data is read from the store. Run artifacts (particles,
        solver grid template) are still discovered on disk when available.

        Parameters
        ----------
        project_dir : Path
            Project root directory.
        store : ResultStore
            An open ResultStore instance.
        """
        project_dir = Path(project_dir).resolve()

        geographic = GeographicArtifacts.from_store(store)

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
