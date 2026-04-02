"""Post-run hook that ingests solver outputs into the ResultStore.

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

from hydromodpy.simulation.results.config import ResultsConfig

logger = logging.getLogger(__name__)

# Mapping solver name → output adapter module/class
_ADAPTER_REGISTRY: dict[str, tuple[str, str]] = {
    "modflownwt": (
        "hydromodpy.simulation.results.adapters.modflownwt",
        "ModflowNwtOutputAdapter",
    ),
    "modflow6": (
        "hydromodpy.simulation.results.adapters.modflow6",
        "Modflow6OutputAdapter",
    ),
    "gr4j": (
        "hydromodpy.simulation.results.adapters.gr4j",
        "GR4JOutputAdapter",
    ),
}


def post_run_results(
    *,
    sim_id: str,
    solver_name: str,
    solver_output_dir: Path | None,
    results_config: ResultsConfig,
    store: Any,
) -> None:
    """Ingest solver outputs into the ResultStore after a run completes.

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
    store : ResultStore
        The open result store.
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
            adapter.extract(sim_id, solver_output_dir, store)
        except Exception:
            logger.exception("Failed to extract outputs for sim %s", sim_id)

    # Phase 2: compute derived variables
    derived_flags = results_config.derived.model_dump()
    try:
        adapter.derive(sim_id, store, derived_flags)
    except Exception:
        logger.exception("Failed to compute derived variables for sim %s", sim_id)

    # Auto-export if configured
    _auto_export(sim_id, store, results_config)

    # Cleanup solver files
    if not results_config.keep_solver_files and solver_output_dir is not None:
        from hydromodpy.simulation.results.adapters.base import cleanup_solver_files
        try:
            cleanup_solver_files(solver_output_dir)
        except Exception:
            logger.warning("Failed to cleanup solver files at %s", solver_output_dir)


def _auto_export(sim_id: str, store: Any, config: ResultsConfig) -> None:
    """Run automated exports based on config."""
    export = config.export
    if not export.any_enabled():
        return

    var_names = export.variables.active_names()
    if not var_names:
        return

    output_dir = Path(export.output_dir) if export.output_dir else None
    if output_dir is None:
        output_dir = store._project_path / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)

    if export.netcdf and var_names:
        try:
            store.export(
                sim_id, ",".join(var_names), "netcdf",
                output_dir / f"{sim_id}.nc",
            )
        except Exception:
            logger.exception("Auto-export NetCDF failed for sim %s", sim_id)

    if export.csv_timeseries:
        try:
            store.export(sim_id, "*", "csv", output_dir / f"{sim_id}_timeseries.csv")
        except Exception:
            logger.exception("Auto-export CSV failed for sim %s", sim_id)

    if export.vtu and var_names:
        for var in var_names:
            try:
                store.export(
                    sim_id, var, "vtu",
                    output_dir / f"{sim_id}_{var}_t0.vtu",
                    timestep=0,
                )
            except Exception:
                logger.exception("Auto-export VTU failed for %s/%s", sim_id, var)

    if export.geotiff and var_names:
        for var in var_names:
            try:
                store.export(
                    sim_id, var, "geotiff",
                    output_dir / f"{sim_id}_{var}_t0.tif",
                    timestep=0,
                )
            except Exception:
                logger.exception("Auto-export GeoTIFF failed for %s/%s", sim_id, var)

    if export.shapefile and var_names:
        for var in var_names:
            try:
                store.export(
                    sim_id, var, "shapefile",
                    output_dir / f"{sim_id}_{var}_t0.shp",
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
