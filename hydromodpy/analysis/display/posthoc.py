"""Post-hoc data reader for the display package.

This module discovers and loads simulation outputs from disk without
requiring runtime objects.  It scans a project's output directories for
geographic artifacts, simulation run outputs, rasters, particles, and
time-series data — everything needed to regenerate figures after a
simulation has completed.

Typical usage::

    ctx = PosthocContext.from_toml("path/to/project.toml")
    for run in ctx.runs:
        print(run.artifact_id, run.watertable_depth_rasters)
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
import warnings


@dataclass(frozen=True)
class GeographicArtifacts:
    """Paths to geographic artifacts in ``results_stable/geographic/``."""

    geographic_dir: Path
    correcflow_dir: Path | None = None
    watershed_shp: Path | None = None
    watershed_dem: Path | None = None
    watershed_box_buff_dem: Path | None = None
    watershed_contour_shp: Path | None = None
    river_network_shp: Path | None = None
    dem_acc_tif: Path | None = None

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

        # River network shapefile (produced when river_network.enabled = true)
        river_shp = _find("river_network", "shp")

        # Flow accumulation raster (always produced by geographic preprocessing)
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


@dataclass(frozen=True, init=False)
class RunArtifacts:
    """Paths to simulation output artifacts for one solver artifact folder."""

    artifact_id: str
    run_dir: Path
    postprocess_dir: Path

    # Solver grid
    solver_grid_template: Path | None = None

    # Watertable arrays (.npy, dict[int, ndarray])
    watertable_elevation_npy: Path | None = None
    watertable_depth_npy: Path | None = None

    # Budget arrays
    outflow_drain_npy: Path | None = None
    seepage_areas_npy: Path | None = None
    groundwater_flux_npy: Path | None = None
    groundwater_storage_npy: Path | None = None
    accumulation_flux_npy: Path | None = None

    # Raster snapshots (list of .tif per stress period)
    watertable_elevation_rasters: list[Path] = field(default_factory=list)
    watertable_depth_rasters: list[Path] = field(default_factory=list)
    seepage_areas_rasters: list[Path] = field(default_factory=list)
    outflow_drain_rasters: list[Path] = field(default_factory=list)

    # Particles
    pathlines_weighted_shp: Path | None = None
    starting_weighted_shp: Path | None = None

    # Simulated time series CSV
    simulated_timeseries_csv: Path | None = None
    native_mesh_figure_dir: Path | None = None

    @property
    def run_id(self) -> str:
        """Deprecated compatibility alias for :attr:`artifact_id`."""
        warnings.warn(
            "'RunArtifacts.run_id' is deprecated. Use 'artifact_id' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.artifact_id

    @property
    def figure_dir(self) -> Path:
        """Return the standard figure directory for this artifact."""
        return self.postprocess_dir / "_figures"

    def __init__(
        self,
        artifact_id: str | None = None,
        run_dir: Path | None = None,
        postprocess_dir: Path | None = None,
        solver_grid_template: Path | None = None,
        watertable_elevation_npy: Path | None = None,
        watertable_depth_npy: Path | None = None,
        outflow_drain_npy: Path | None = None,
        seepage_areas_npy: Path | None = None,
        groundwater_flux_npy: Path | None = None,
        groundwater_storage_npy: Path | None = None,
        accumulation_flux_npy: Path | None = None,
        watertable_elevation_rasters: list[Path] | None = None,
        watertable_depth_rasters: list[Path] | None = None,
        seepage_areas_rasters: list[Path] | None = None,
        outflow_drain_rasters: list[Path] | None = None,
        pathlines_weighted_shp: Path | None = None,
        starting_weighted_shp: Path | None = None,
        simulated_timeseries_csv: Path | None = None,
        native_mesh_figure_dir: Path | None = None,
        *,
        run_id: str | None = None,
    ) -> None:
        resolved_artifact_id = _resolve_deprecated_run_id_alias(
            artifact_id=artifact_id,
            run_id=run_id,
        )
        object.__setattr__(self, "artifact_id", resolved_artifact_id)
        object.__setattr__(self, "run_dir", run_dir)
        object.__setattr__(self, "postprocess_dir", postprocess_dir)
        object.__setattr__(self, "solver_grid_template", solver_grid_template)
        object.__setattr__(self, "watertable_elevation_npy", watertable_elevation_npy)
        object.__setattr__(self, "watertable_depth_npy", watertable_depth_npy)
        object.__setattr__(self, "outflow_drain_npy", outflow_drain_npy)
        object.__setattr__(self, "seepage_areas_npy", seepage_areas_npy)
        object.__setattr__(self, "groundwater_flux_npy", groundwater_flux_npy)
        object.__setattr__(self, "groundwater_storage_npy", groundwater_storage_npy)
        object.__setattr__(self, "accumulation_flux_npy", accumulation_flux_npy)
        object.__setattr__(
            self,
            "watertable_elevation_rasters",
            [] if watertable_elevation_rasters is None else list(watertable_elevation_rasters),
        )
        object.__setattr__(
            self,
            "watertable_depth_rasters",
            [] if watertable_depth_rasters is None else list(watertable_depth_rasters),
        )
        object.__setattr__(
            self,
            "seepage_areas_rasters",
            [] if seepage_areas_rasters is None else list(seepage_areas_rasters),
        )
        object.__setattr__(
            self,
            "outflow_drain_rasters",
            [] if outflow_drain_rasters is None else list(outflow_drain_rasters),
        )
        object.__setattr__(self, "pathlines_weighted_shp", pathlines_weighted_shp)
        object.__setattr__(self, "starting_weighted_shp", starting_weighted_shp)
        object.__setattr__(self, "simulated_timeseries_csv", simulated_timeseries_csv)
        object.__setattr__(self, "native_mesh_figure_dir", native_mesh_figure_dir)

    @classmethod
    def discover(cls, run_dir: Path) -> RunArtifacts:
        """Scan a run directory and return found artifacts."""
        run_id = run_dir.name
        pp = run_dir / "_postprocess"

        def _npy(name: str) -> Path | None:
            p = pp / f"{name}.npy"
            return p if p.exists() else None

        def _rasters(prefix: str) -> list[Path]:
            rasters_dir = pp / "_rasters"
            if not rasters_dir.is_dir():
                return []
            return sorted(rasters_dir.glob(f"{prefix}_t(*).tif"))

        def _particle_shp(name: str) -> Path | None:
            p = pp / "_particles" / f"{name}.shp"
            return p if p.exists() else None

        solver_tpl = run_dir / "_solver_grid_template.tif"
        ts_csv = pp / "_timeseries" / "_simulated_timeseries.csv"
        native_mesh_figure_dir = pp / "_figures" / "native_mesh"

        return cls(
            artifact_id=run_id,
            run_dir=run_dir,
            postprocess_dir=pp,
            solver_grid_template=solver_tpl if solver_tpl.exists() else None,
            watertable_elevation_npy=_npy("watertable_elevation"),
            watertable_depth_npy=_npy("watertable_depth"),
            outflow_drain_npy=_npy("outflow_drain"),
            seepage_areas_npy=_npy("seepage_areas"),
            groundwater_flux_npy=_npy("groundwater_flux"),
            groundwater_storage_npy=_npy("groundwater_storage"),
            accumulation_flux_npy=_npy("accumulation_flux"),
            watertable_elevation_rasters=_rasters("watertable_elevation"),
            watertable_depth_rasters=_rasters("watertable_depth"),
            seepage_areas_rasters=_rasters("seepage_areas"),
            outflow_drain_rasters=_rasters("outflow_drain"),
            pathlines_weighted_shp=_particle_shp("pathlines_weighted"),
            starting_weighted_shp=_particle_shp("starting_weighted"),
            simulated_timeseries_csv=ts_csv if ts_csv.exists() else None,
            native_mesh_figure_dir=(
                native_mesh_figure_dir if native_mesh_figure_dir.is_dir() else None
            ),
        )

    def base_raster(self, geographic: GeographicArtifacts) -> Path | None:
        """Return the best available base raster for map overlays."""
        if self.solver_grid_template is not None:
            return self.solver_grid_template
        return geographic.watershed_dem


def _resolve_deprecated_run_id_alias(
    *,
    artifact_id: str | None,
    run_id: str | None,
) -> str:
    """Resolve one canonical artifact identifier from modern and legacy names."""
    normalized_artifact_id = str(artifact_id or "").strip()
    normalized_run_id = str(run_id or "").strip()
    if normalized_artifact_id and normalized_run_id and normalized_artifact_id != normalized_run_id:
        raise ValueError(
            f"RunArtifacts received both artifact_id={normalized_artifact_id!r} "
            f"and run_id={normalized_run_id!r}; use only one identifier."
        )
    if normalized_artifact_id:
        return normalized_artifact_id
    if normalized_run_id:
        warnings.warn(
            "'RunArtifacts(run_id=...)' is deprecated. Use 'artifact_id=' instead.",
            DeprecationWarning,
            stacklevel=3,
        )
        return normalized_run_id
    raise TypeError("RunArtifacts requires 'artifact_id' (or deprecated 'run_id').")


@dataclass(frozen=True)
class PosthocContext:
    """Complete post-hoc context for one project."""

    project_dir: Path
    geographic: GeographicArtifacts
    runs: list[RunArtifacts]

    @classmethod
    def from_project_dir(cls, project_dir: Path) -> PosthocContext:
        """Build a context by scanning ``results_stable/`` and ``results_simulations/``."""
        project_dir = Path(project_dir).resolve()

        geo_dir = project_dir / "results_stable" / "geographic"
        geographic = GeographicArtifacts.discover(geo_dir)

        sims_dir = project_dir / "results_simulations"
        runs: list[RunArtifacts] = []
        if sims_dir.is_dir():
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

        Resolve the effective project directory from ``[workspace].project_root``
        when present, otherwise fall back to the TOML parent directory.
        """
        toml_path = Path(toml_path).resolve()
        with open(toml_path, "rb") as handle:
            raw = tomllib.load(handle)
        workspace = raw.get("workspace", {})
        project_root = workspace.get("project_root")
        if project_root:
            return cls.from_project_dir((toml_path.parent / project_root).resolve())
        return cls.from_project_dir(toml_path.parent)
