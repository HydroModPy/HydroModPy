"""Post-run hook that ingests solver outputs into the Catalog.

Called by ``SimulationRunner`` after each solver execution completes.
Orchestrates the full results lifecycle: extract → derive → export →
cleanup → provenance.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hydromodpy.core.contracts.solver_registry import get_solver_registry_provider
from hydromodpy.core.logging import get_logger
from hydromodpy.simulation.planning.export_config import ExportConfig
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.simulation.planning.results_config import ResultsConfig

logger = get_logger(__name__)


def record_run_execution_metrics(
    *,
    ctx: RunContext,
    sim_id: str,
    store: Any,
    result: RunExecutionResult,
) -> None:
    """Persist lightweight solver-side execution metrics in the catalog."""
    if not ctx.run.is_solver_backed:
        return
    if store is None or sim_id in (None, ""):
        return
    metrics = getattr(result, "metrics", None)
    if not isinstance(metrics, Mapping):
        return
    for metric_name, raw_value in metrics.items():
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(value):
            continue
        store.write_metric(
            sim_id,
            station_id=str(ctx.run.id),
            variable="runtime",
            metric_name=str(metric_name),
            value=value,
        )


def post_run_results(
    *,
    ctx: RunContext,
    sim_id: str,
    results_config: ResultsConfig,
    store: Any,
    export_config: ExportConfig | None = None,
    keep_solver_files: bool | None = None,
    run_id: str | None = None,
) -> None:
    """Ingest solver outputs into the Catalog after a run completes.

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
    store : Catalog
        The open result store.
    export_config : ExportConfig, optional
        The top-level ``[export]`` block. Defaults to :class:`ExportConfig`.
    run_id : str, optional
        Human-readable run identifier used to name export subdirectories.
        Falls back to the first 8 characters of *sim_id* when absent.
    """
    if not ctx.run.is_solver_backed:
        return
    if not results_config.persistence.save_catalog:
        return

    extract_run_outputs(
        ctx=ctx,
        sim_id=sim_id,
        results_config=results_config,
        store=store,
    )
    derive_run_outputs(
        ctx=ctx,
        sim_id=sim_id,
        results_config=results_config,
        store=store,
    )
    auto_export_results(
        sim_id=sim_id,
        store=store,
        export_config=export_config or ExportConfig(),
        save_catalog=results_config.persistence.save_catalog,
        run_id=run_id,
    )
    cleanup_solver_outputs(
        ctx=ctx,
        results_config=results_config,
        keep_solver_files=keep_solver_files,
    )


def extract_run_outputs(
    *,
    ctx: RunContext,
    sim_id: str,
    results_config: ResultsConfig,
    store: Any,
) -> None:
    """Extract raw solver outputs into the Catalog."""
    if not ctx.run.is_solver_backed:
        return
    if not results_config.persistence.save_catalog:
        return

    provider = get_solver_registry_provider()
    solver_name = ctx.run.solver
    solver_output_dir = ctx.state.execution.output_dirs_by_run_id.get(ctx.run.id)

    extractor = provider.get_extractor_instance(ctx.run.process_type, solver_name)
    if extractor is None:
        raise RuntimeError(f"No output adapter registered for {ctx.run.process_type}/{solver_name}")

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
    start_datetime = _resolve_run_start_datetime(ctx)
    if start_datetime is not None and _accepts_kwarg(extractor.extract, "start_datetime"):
        extract_kwargs["start_datetime"] = start_datetime
    extractor.extract(sim_id, solver_output_dir, store, **extract_kwargs)

    _finalize_run_provenance(ctx=ctx, sim_id=sim_id, store=store)


def _run_model(ctx: RunContext) -> Any:
    """Return the model the runner produced for this run, or None."""
    execution = getattr(getattr(ctx, "state", None), "execution", None)
    models = getattr(execution, "models_by_run_id", None)
    if isinstance(models, Mapping):
        return models.get(ctx.run.id)
    return None


def _finalize_run_provenance(*, ctx: RunContext, sim_id: str, store: Any) -> None:
    """Backfill provenance known only after the solver grid is built and run.

    The simulation row is registered before the solver grid exists (NULL grid
    metadata for DISV-from-raster runs), and the recorded binary is a best guess;
    both are refined here from the model the run actually produced.
    """
    model = _run_model(ctx)
    if model is None:
        return
    grid = _resolve_run_grid_metadata(model)
    if grid is not None:
        try:
            store.update_simulation_grid_metadata(sim_id, **grid)
        except Exception:
            logger.debug("Could not backfill grid metadata for sim %s", sim_id, exc_info=True)
    binary_path = getattr(model, "exe", None)
    if binary_path:
        try:
            store.update_run_environment_solver_binary(sim_id, solver_binary_path=binary_path)
        except Exception:
            logger.debug(
                "Could not refine solver binary identity for sim %s", sim_id, exc_info=True
            )


def _resolve_run_grid_metadata(model: Any) -> dict | None:
    """Duck-type grid metadata (n_cells, n_layers, bbox, hash, topology) off a model."""
    solver_mesh = getattr(model, "solver_mesh", None)
    if solver_mesh is None:
        return None
    import hashlib

    import numpy as np

    n_cells = getattr(solver_mesh, "n_cells", None)
    n_layers = getattr(solver_mesh, "nlay", None)
    meta: dict[str, Any] = {
        "n_cells": None if n_cells is None else int(n_cells),
        "n_layers": None if n_layers is None else int(n_layers),
    }
    try:
        dims = "3d" if int(n_layers or 1) > 1 else "2d"
        kind = "structured" if bool(solver_mesh.is_structured) else "unstructured"
        meta["mesh_topology"] = f"{kind}_{dims}"
    except Exception:
        pass
    planar = getattr(solver_mesh, "planar_mesh", None)
    if planar is None:
        return meta
    try:
        # HydroMesh.bounds() -> (xmin, ymin, [zmin,] xmax, ymax, [zmax]); keep XY.
        raw_bounds = planar.bounds
        raw_bounds = raw_bounds() if callable(raw_bounds) else raw_bounds
        bounds = tuple(float(v) for v in raw_bounds)
        if len(bounds) >= 4:
            half = len(bounds) // 2
            meta["bbox"] = [bounds[0], bounds[1], bounds[half], bounds[half + 1]]
    except Exception:
        pass
    try:
        vertices = np.asarray(planar.vertices, dtype=float)
        connectivity = np.asarray(planar.flat_connectivity)
        meta["mesh_hash"] = hashlib.sha256(vertices.tobytes() + connectivity.tobytes()).hexdigest()
    except Exception:
        pass
    return meta


def _resolve_run_start_datetime(ctx: RunContext) -> str | None:
    """Return the simulation start as an ISO string, or None.

    The /time CF coordinate is written by each extractor at field-array
    resolution (one entry per solver output time). Backends whose output carries
    no calendar (MODFLOW-2005/NWT, Boussinesq) anchor it to this start so the
    axis decodes to real dates instead of relative seconds since 1970.
    """
    setup = getattr(getattr(ctx, "state", None), "setup", None)
    time_grid = getattr(setup, "time_grid", None)
    if time_grid is None:
        return None
    boundaries = getattr(time_grid, "boundaries", None)
    if boundaries:
        return str(boundaries[0])
    window = getattr(time_grid, "window", None)
    start = getattr(window, "start", None)
    if start is not None:
        return str(start)
    datetimes = getattr(time_grid, "datetimes", None)
    if datetimes:
        return str(datetimes[0])
    return None


def derive_run_outputs(
    *,
    ctx: RunContext,
    sim_id: str,
    results_config: ResultsConfig,
    store: Any,
) -> None:
    """Compute solver-adapter derived outputs and catchment aggregates."""
    if not ctx.run.is_solver_backed:
        return
    if not results_config.persistence.save_catalog:
        return

    provider = get_solver_registry_provider()
    solver_name = ctx.run.solver
    extractor = provider.get_extractor_instance(ctx.run.process_type, solver_name)
    if extractor is None:
        raise RuntimeError(f"No output adapter registered for {ctx.run.process_type}/{solver_name}")

    derived_flags = results_config.derived.model_dump()
    extractor.derive(sim_id, store, derived_flags)

    # Phase 3: aggregate catchment timeseries from spatial fields
    if getattr(extractor, "category", None) != "lumped":
        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            aggregate_catchment_timeseries,
        )

        aggregate_catchment_timeseries(sim_id, store)


def auto_export_results(
    *,
    sim_id: str,
    store: Any,
    export_config: ExportConfig,
    save_catalog: bool,
    run_id: str | None = None,
) -> None:
    """Run automated exports for one simulation when configured."""
    if not save_catalog:
        return

    export_label = run_id or sim_id[:8]
    _auto_export(sim_id, store, export_config, export_label=export_label)


def auto_export_package(
    *,
    sim_id: str,
    store: Any,
    export_config: ExportConfig,
    save_catalog: bool,
    run_id: str | None = None,
) -> None:
    """Write the portable ``.hmp`` archive when ``[export].package`` is set.

    Called while the store is still open (just before ``step_finalize_store``
    closes it). The ``.hmp`` exporter repacks the live Zarr itself, so it does
    not need the finalized ``.zarr.zip``.
    """
    if not save_catalog or not export_config.package:
        return

    label = run_id or sim_id[:8]
    base_dir = (
        Path(export_config.output_dir)
        if export_config.output_dir
        else store.project_path / "exports"
    )
    output_dir = base_dir / label
    output_dir.mkdir(parents=True, exist_ok=True)
    dest = output_dir / f"{Path(label).name}.hmp"
    store.export_package(sim_id, dest)
    store.record_export(sim_id, kind="hmp", path=dest)
    _write_run_card(output_dir, sim_id, label)


def cleanup_solver_outputs(
    *,
    ctx: RunContext,
    results_config: ResultsConfig,
    keep_solver_files: bool | None = None,
) -> None:
    """Cleanup raw solver files through the matching solver adapter."""
    if not ctx.run.is_solver_backed:
        return
    do_keep = (
        keep_solver_files if keep_solver_files is not None else results_config.keep_solver_files
    )
    if do_keep:
        return
    provider = get_solver_registry_provider()
    try:
        adapter = provider.get_solver_adapter(ctx.run.process_type, ctx.run.solver)
    except KeyError:
        logger.debug(
            "No solver adapter registered for %s/%s, skipping cleanup",
            ctx.run.process_type,
            ctx.run.solver,
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


def _single_timestep(times: Any) -> int | str:
    """Collapse a times selector to one timestep for single-timestep formats."""
    if isinstance(times, int):
        return times
    if isinstance(times, list):
        return times[-1] if times else "last"
    if times == "all":
        return "last"
    return times


def _time_token(selector: int | str) -> str:
    """Filename token for a single-timestep selector (e.g. 't3', 'last')."""
    return f"t{selector}" if isinstance(selector, int) else str(selector)


def _auto_export(
    sim_id: str,
    store: Any,
    export: ExportConfig,
    *,
    export_label: str = "",
) -> None:
    """Run automated exports based on the top-level ``[export]`` config.

    Exports are written to ``exports/{export_label}/`` so that the
    directory tree is organized by human-readable run name, not UUID.
    """
    from hydromodpy.core.config_kit.export_spec import ExportSpec

    label = export_label or sim_id[:8]
    base_dir = Path(export.output_dir) if export.output_dir else store.project_path / "exports"
    output_dir = base_dir / label

    specs: list[ExportSpec] = []

    # Format toggles -> one spec per artifact. Single-timestep rasters use the
    # configured times selector collapsed to one step; NetCDF honors the full
    # selector (it is multi-step capable).
    if export.any_enabled():
        var_names = export.variables.active_names()
        raster_time = _single_timestep(export.times)
        token = _time_token(raster_time)
        if export.csv_timeseries:
            specs.append(ExportSpec(var="*", dest=output_dir / "timeseries.csv"))
        if var_names:
            if export.netcdf:
                specs.append(
                    ExportSpec(
                        var=list(var_names), dest=output_dir / "fields.nc", time=export.times
                    )
                )
            for var in var_names:
                if export.vtu:
                    specs.append(
                        ExportSpec(
                            var=var, dest=output_dir / f"{var}_{token}.vtu", time=raster_time
                        )
                    )
                if export.geotiff:
                    specs.append(
                        ExportSpec(
                            var=var,
                            dest=output_dir / f"{var}_{token}.tif",
                            time=raster_time,
                            resolution=export.resolution,
                        )
                    )
                if export.shapefile:
                    specs.append(
                        ExportSpec(
                            var=var, dest=output_dir / f"{var}_{token}.shp", time=raster_time
                        )
                    )

    # Explicit artifact specs (the full contract). Relative dests resolve under
    # the run export directory; absolute dests are kept verbatim.
    for art in export.artifacts:
        dest = art.dest if art.dest.is_absolute() else output_dir / art.dest
        specs.append(art.model_copy(update={"dest": dest}))

    if not specs:
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    _write_run_card(output_dir, sim_id, label)
    failures: list[str] = []
    for spec in specs:
        try:
            out_path = store.export(sim_id, spec)
            kind = spec.fmt.value if spec.fmt is not None else Path(out_path).suffix.lstrip(".")
            store.record_export(sim_id, kind=kind, path=out_path)
        except Exception as exc:
            failures.append(f"{Path(spec.dest).name}: {exc}")

    if failures:
        raise RuntimeError(f"Auto-export failed for sim {sim_id}: " + "; ".join(failures))


def _write_run_card(output_dir: Path, sim_id: str, label: str) -> None:
    """Write a small RUN.txt so a copied export folder stays self-identifying."""
    try:
        (output_dir / "RUN.txt").write_text(
            f"name: {label}\nid: {sim_id[:8]}\nsim_id: {sim_id}\n", encoding="utf-8"
        )
    except OSError:
        pass
