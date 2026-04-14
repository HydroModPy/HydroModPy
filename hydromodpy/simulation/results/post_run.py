"""Post-run hook that ingests solver outputs into the SimulationCatalog.

Called by ``SimulationRunner`` after each solver execution completes.
Orchestrates the full results lifecycle: extract → derive → export →
cleanup → provenance.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from hydromodpy.results.config import ResultsConfig

logger = logging.getLogger(__name__)

# Mapping solver name → output adapter module/class
_ADAPTER_REGISTRY: dict[str, tuple[str, str]] = {
    "modflownwt": (
        "hydromodpy.simulation.results.extractors.modflownwt",
        "ModflowNwtOutputAdapter",
    ),
    "modflow6": (
        "hydromodpy.simulation.results.extractors.modflow6",
        "Modflow6OutputAdapter",
    ),
    "gr4j": (
        "hydromodpy.simulation.results.extractors.gr4j",
        "GR4JOutputAdapter",
    ),
    "mt3dms": (
        "hydromodpy.simulation.results.extractors.mt3dms",
        "Mt3dmsOutputAdapter",
    ),
    "modflow6gwt": (
        "hydromodpy.simulation.results.extractors.mt3dms",
        "Mt3dmsOutputAdapter",
    ),
    "modpath": (
        "hydromodpy.simulation.results.extractors.modpath",
        "ModpathOutputAdapter",
    ),
    "boussinesq": (
        "hydromodpy.simulation.results.extractors.boussinesq",
        "BoussinesqOutputAdapter",
    ),
}


def post_run_results(
    *,
    sim_id: str,
    solver_name: str,
    solver_output_dir: Path | None,
    results_config: ResultsConfig,
    store: Any,
    keep_solver_files: bool | None = None,
    run_id: str | None = None,
) -> None:
    """Ingest solver outputs into the SimulationCatalog after a run completes.

    Parameters
    ----------
    sim_id : str
        Simulation UUID.
    solver_name : str
        Solver that just completed (e.g. ``"modflownwt"``).
    solver_output_dir : Path or None
        Directory containing raw solver output files. ``None`` for
        in-memory solvers (GR4J).
    results_config : ResultsConfig
        The ``[simulation.results]`` config block.
    store : SimulationCatalog
        The open result store.
    run_id : str, optional
        Human-readable run identifier used to name export subdirectories.
        Falls back to the first 8 characters of *sim_id* when absent.
    """
    if not results_config.store:
        return

    adapter = _get_output_adapter(solver_name)
    if adapter is None:
        logger.debug("No output adapter for solver '%s', skipping results ingestion", solver_name)
        return

    # Phase 1: extract raw outputs
    if solver_output_dir is not None and solver_output_dir.exists():
        try:
            # Pass budget_spatial_fields if the adapter supports it.
            extract_kwargs = {}
            if results_config.budget.spatial_fields:
                extract_kwargs["budget_spatial_fields"] = True
            adapter.extract(sim_id, solver_output_dir, store, **extract_kwargs)
        except TypeError:
            # Adapter doesn't accept extra kwargs (Boussinesq, GR4J, etc.)
            try:
                adapter.extract(sim_id, solver_output_dir, store)
            except Exception:
                logger.exception("Failed to extract outputs for sim %s", sim_id)
        except Exception:
            logger.exception("Failed to extract outputs for sim %s", sim_id)

    # Phase 2: compute derived variables
    derived_flags = results_config.derived.model_dump()
    try:
        adapter.derive(sim_id, store, derived_flags)
    except Exception:
        logger.exception("Failed to compute derived variables for sim %s", sim_id)

    # Phase 3: aggregate catchment timeseries from spatial fields
    try:
        from hydromodpy.simulation.results.extractors.catchment_aggregation import (
            aggregate_catchment_timeseries,
        )
        aggregate_catchment_timeseries(sim_id, store)
    except Exception:
        logger.exception("Failed to aggregate catchment timeseries for sim %s", sim_id)

    # Auto-export if configured
    export_label = run_id or sim_id[:8]
    _auto_export(sim_id, store, results_config, export_label=export_label)

    # Cleanup solver files
    do_keep = keep_solver_files if keep_solver_files is not None else results_config.keep_solver_files
    if not do_keep and solver_output_dir is not None:
        from hydromodpy.simulation.results.extractors.base import cleanup_solver_files
        try:
            cleanup_solver_files(solver_output_dir)
        except Exception:
            logger.warning("Failed to cleanup solver files at %s", solver_output_dir)


def _auto_export(
    sim_id: str,
    store: Any,
    config: ResultsConfig,
    *,
    export_label: str = "",
) -> None:
    """Run automated exports based on config.

    Exports are written to ``exports/{export_label}/`` so that the
    directory tree is organized by human-readable run name, not UUID.
    """
    export = config.export
    if not export.any_enabled():
        return

    var_names = export.variables.active_names()
    if not var_names:
        return

    label = export_label or sim_id[:8]
    base_dir = Path(export.output_dir) if export.output_dir else None
    if base_dir is None:
        base_dir = store.project_path / "exports"
    output_dir = base_dir / label
    output_dir.mkdir(parents=True, exist_ok=True)

    if export.csv_timeseries:
        try:
            store.export(sim_id, "*", "csv", output_dir / "timeseries.csv")
        except Exception:
            logger.exception("Auto-export CSV failed for sim %s", sim_id)

    if export.netcdf and var_names:
        try:
            store.export(
                sim_id, ",".join(var_names), "netcdf",
                output_dir / "fields.nc",
            )
        except KeyError:
            logger.debug("NetCDF export skipped (no UGRID mesh) for sim %s", sim_id)
        except Exception:
            logger.exception("Auto-export NetCDF failed for sim %s", sim_id)

    if export.vtu and var_names:
        for var in var_names:
            try:
                store.export(
                    sim_id, var, "vtu",
                    output_dir / f"{var}_t0.vtu",
                    timestep=0,
                )
            except Exception:
                logger.exception("Auto-export VTU failed for %s/%s", sim_id, var)

    if export.geotiff and var_names:
        for var in var_names:
            try:
                store.export(
                    sim_id, var, "geotiff",
                    output_dir / f"{var}_t0.tif",
                    timestep=0,
                )
            except Exception:
                logger.exception("Auto-export GeoTIFF failed for %s/%s", sim_id, var)

    if export.shapefile and var_names:
        for var in var_names:
            try:
                store.export(
                    sim_id, var, "shapefile",
                    output_dir / f"{var}_t0.shp",
                    timestep=0,
                )
            except Exception:
                logger.exception("Auto-export Shapefile failed for %s/%s", sim_id, var)


def _get_output_adapter(solver_name: str):
    """Lazily import and instantiate the output adapter for a solver."""
    entry = _ADAPTER_REGISTRY.get(solver_name)
    if entry is None:
        return None
    import importlib
    module_path, class_name = entry
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls()
