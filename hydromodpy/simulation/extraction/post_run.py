"""Post-run hook that ingests solver outputs into the SimulationCatalog.

Called by ``SimulationRunner`` after each solver execution completes.
Orchestrates the full results lifecycle: extract → derive → export →
cleanup → provenance.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.config.results_config import ResultsConfig
from hydromodpy.core.logging import get_logger
from hydromodpy.simulation.planning.plan import RunContext
from hydromodpy.solver.base.registry import get_extractor_instance, get_solver_adapter

logger = get_logger(__name__)


def post_run_results(
    *,
    ctx: RunContext,
    sim_id: str,
    results_config: ResultsConfig,
    store: Any,
    keep_solver_files: bool | None = None,
    run_id: str | None = None,
) -> None:
    """Ingest solver outputs into the SimulationCatalog after a run completes.

    Parameters
    ----------
    ctx : RunContext
        Resolved runtime context for the run that just completed. Carries
        the ``ProcessRun`` (process type and solver name) and the runtime
        state used to locate the scratch directory.
    sim_id : str
        Simulation UUID.
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

    solver_name = ctx.run.solver
    solver_output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)

    extractor = get_extractor_instance(solver_name)
    if extractor is None:
        logger.debug("No output adapter for solver '%s', skipping results ingestion", solver_name)
        return

    # Phase 1: extract raw outputs
    if solver_output_dir is not None and solver_output_dir.exists():
        try:
            extract_kwargs = {}
            if results_config.budget.spatial_fields:
                extract_kwargs["budget_spatial_fields"] = True
            extractor.extract(sim_id, solver_output_dir, store, **extract_kwargs)
        except TypeError:
            # Extractor doesn't accept extra kwargs (Boussinesq, GR4J, etc.)
            try:
                extractor.extract(sim_id, solver_output_dir, store)
            except Exception:
                logger.exception("Failed to extract outputs for sim %s", sim_id)
        except Exception:
            logger.exception("Failed to extract outputs for sim %s", sim_id)

    # Phase 2: compute derived variables
    derived_flags = results_config.derived.model_dump()
    try:
        extractor.derive(sim_id, store, derived_flags)
    except Exception:
        logger.exception("Failed to compute derived variables for sim %s", sim_id)

    # Phase 3: aggregate catchment timeseries from spatial fields
    try:
        from hydromodpy.simulation.extraction.extractors.catchment_aggregation import (
            aggregate_catchment_timeseries,
        )

        aggregate_catchment_timeseries(sim_id, store)
    except Exception:
        logger.exception("Failed to aggregate catchment timeseries for sim %s", sim_id)

    # Auto-export if configured
    export_label = run_id or sim_id[:8]
    _auto_export(sim_id, store, results_config, export_label=export_label)

    # Cleanup solver files via the solver adapter
    do_keep = (
        keep_solver_files if keep_solver_files is not None else results_config.keep_solver_files
    )
    if not do_keep:
        try:
            adapter = get_solver_adapter(ctx.run.process_type, solver_name)
        except KeyError:
            logger.debug(
                "No solver adapter registered for %s/%s, skipping cleanup",
                ctx.run.process_type,
                solver_name,
            )
            return
        try:
            adapter.cleanup(ctx)
        except Exception:
            logger.warning("Failed to cleanup solver files for run %s", ctx.run.id)


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
                sim_id,
                ",".join(var_names),
                "netcdf",
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
                    sim_id,
                    var,
                    "vtu",
                    output_dir / f"{var}_t0.vtu",
                    timestep=0,
                )
            except Exception:
                logger.exception("Auto-export VTU failed for %s/%s", sim_id, var)

    if export.geotiff and var_names:
        for var in var_names:
            try:
                store.export(
                    sim_id,
                    var,
                    "geotiff",
                    output_dir / f"{var}_t0.tif",
                    timestep=0,
                )
            except Exception:
                logger.exception("Auto-export GeoTIFF failed for %s/%s", sim_id, var)

    if export.shapefile and var_names:
        for var in var_names:
            try:
                store.export(
                    sim_id,
                    var,
                    "shapefile",
                    output_dir / f"{var}_t0.shp",
                    timestep=0,
                )
            except Exception:
                logger.exception("Auto-export Shapefile failed for %s/%s", sim_id, var)
