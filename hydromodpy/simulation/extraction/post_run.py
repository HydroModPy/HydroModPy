"""Post-run hook that ingests solver outputs into the SimulationCatalog.

Called by ``SimulationRunner`` after each solver execution completes.
Orchestrates the full results lifecycle: extract → derive → export →
cleanup → provenance.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.simulation._solver_protocol import get_solver_registry_provider
from hydromodpy.simulation.planning.plan import RunContext
from hydromodpy.simulation.planning.results_config import ResultsConfig

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
    if not results_config.persistence.save_catalog:
        return

    provider = get_solver_registry_provider()
    solver_name = ctx.run.solver
    solver_output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)

    extractor = provider.get_extractor_instance(solver_name)
    if extractor is None:
        raise RuntimeError(f"No output adapter registered for solver {solver_name!r}")

    # Phase 1: extract raw outputs
    if solver_output_dir is None or not solver_output_dir.exists():
        raise FileNotFoundError(
            f"Solver output directory is missing for sim {sim_id}: {solver_output_dir}"
        )

    extract_kwargs = {}
    if results_config.budget.spatial_fields and _accepts_kwarg(
        extractor.extract,
        "budget_spatial_fields",
    ):
        extract_kwargs["budget_spatial_fields"] = True
    extractor.extract(sim_id, solver_output_dir, store, **extract_kwargs)

    # Phase 2: compute derived variables
    derived_flags = results_config.derived.model_dump()
    extractor.derive(sim_id, store, derived_flags)

    # Phase 3: aggregate catchment timeseries from spatial fields
    if getattr(extractor, "category", None) != "lumped":
        from hydromodpy.simulation.extraction.extractors.catchment_aggregation import (
            aggregate_catchment_timeseries,
        )

        aggregate_catchment_timeseries(sim_id, store)

    # Auto-export if configured
    export_label = run_id or sim_id[:8]
    _auto_export(sim_id, store, results_config, export_label=export_label)

    # Cleanup solver files via the solver adapter
    do_keep = (
        keep_solver_files if keep_solver_files is not None else results_config.keep_solver_files
    )
    if not do_keep:
        try:
            adapter = provider.get_solver_adapter(ctx.run.process_type, solver_name)
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
            logger.warning("Failed to cleanup solver files for run %s", ctx.run.id, exc_info=True)


def _accepts_kwarg(callable_obj: Any, name: str) -> bool:
    """Return True when ``callable_obj`` accepts keyword ``name``."""
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return False
    return name in signature.parameters or any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()
    )


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

    failures: list[str] = []

    if export.csv_timeseries:
        try:
            store.export(sim_id, "*", "csv", output_dir / "timeseries.csv")
        except Exception as exc:
            failures.append(f"csv: {exc}")

    if export.netcdf and var_names:
        try:
            store.export(
                sim_id,
                ",".join(var_names),
                "netcdf",
                output_dir / "fields.nc",
            )
        except Exception as exc:
            failures.append(f"netcdf: {exc}")

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
            except Exception as exc:
                failures.append(f"vtu:{var}: {exc}")

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
            except Exception as exc:
                failures.append(f"geotiff:{var}: {exc}")

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
            except Exception as exc:
                failures.append(f"shapefile:{var}: {exc}")

    if failures:
        raise RuntimeError(f"Auto-export failed for sim {sim_id}: " + "; ".join(failures))
