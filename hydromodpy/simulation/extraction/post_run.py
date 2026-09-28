"""Post-run hook that ingests solver outputs into the Catalog.

Called by ``SimulationRunner`` after each solver execution completes.
Orchestrates the full results lifecycle: extract → derive → export →
cleanup → provenance.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hydromodpy.core.config_kit.export_spec import RUN_FORMATS, ExportRequest
from hydromodpy.core.contracts.solver_registry import get_solver_registry_provider
from hydromodpy.core.logging import get_logger
from hydromodpy.core.progress import MILESTONE
from hydromodpy.core.state.paths import display_path, share_dir_for
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
    export_requests: Sequence[ExportRequest] = (),
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
    export_requests : sequence of ExportRequest, optional
        The ``[[export]]`` blocks of the run, in the order of the file. The
        package and metadata requests are left to :func:`auto_export_package`,
        which runs on the sealed run.
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
    written = auto_export_results(
        sim_id=sim_id,
        store=store,
        export_requests=export_requests,
        save_catalog=results_config.persistence.save_catalog,
        run_id=run_id,
    )
    announce_exports(written, share_dir_for(store.project_path) / (run_id or sim_id[:8]))
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
    solver_output_dir = ctx.output_dir

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
    for keyword, value in _dry_cell_sentinels(ctx).items():
        if _accepts_kwarg(extractor.extract, keyword):
            extract_kwargs[keyword] = value
    extractor.extract(sim_id, solver_output_dir, store, **extract_kwargs)

    _finalize_run_provenance(ctx=ctx, sim_id=sim_id, store=store)


def _finalize_run_provenance(*, ctx: RunContext, sim_id: str, store: Any) -> None:
    """Backfill provenance known only after the solver grid is built and run.

    The simulation row is registered before the solver grid exists (NULL grid
    metadata for DISV-from-raster runs), and the recorded binary is a best guess;
    both are refined here from the model the run actually produced.
    """
    model = ctx.model
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
        conn = planar.flat_connectivity  # rectangular array or ragged POLYGON tuple
        conn_bytes = (
            b"".join(np.asarray(c, dtype=np.int64).tobytes() for c in conn)
            if isinstance(conn, tuple)
            else np.asarray(conn, dtype=np.int64).tobytes()
        )
        meta["mesh_hash"] = hashlib.sha256(vertices.tobytes() + conn_bytes).hexdigest()
    except Exception:
        pass
    return meta


def _dry_cell_sentinels(ctx: RunContext) -> dict[str, float]:
    """Return the head sentinels the solver was configured to write.

    MODFLOW-NWT stamps dry cells with ``[modflownwt.runtime.upw] hdry`` and
    inactive cells with ``[modflownwt.runtime.bas] hnoflo``; the extractor
    masks exactly those values to NaN. Reading them back from defaults would
    keep -100 and -9999 in the heads of anyone who changed them.
    """
    runtime = ctx.state.cfg.modflownwt.runtime
    return {"hdry": float(runtime.upw.hdry), "hnoflo": float(runtime.bas.hnoflo)}


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

    # The discharge band the drains were given changes what "this cell seeps"
    # means, so it has to be in the store BEFORE anything derives a seepage
    # mask from it, and it has to stay there for every figure drawn afterwards.
    # Written here rather than in the workflow step because this function is
    # the one funnel both the step and the direct post-run path go through.
    sim_zarr = store.open_zarr(sim_id)
    try:
        sim_zarr.drain_band_depth_m = float(ctx.state.cfg.solver.drain_band_depth_m)
    finally:
        sim_zarr.close()

    derived_flags = results_config.derived.model_dump()
    extractor.derive(sim_id, store, derived_flags)

    # Phase 3: aggregate catchment timeseries from spatial fields
    if getattr(extractor, "category", None) != "lumped":
        from hydromodpy.simulation.extraction.derivation.catchment_aggregation import (
            aggregate_catchment_timeseries,
        )

        aggregate_catchment_timeseries(sim_id, store)

    sample_declared_observation_points(ctx=ctx, sim_id=sim_id, store=store)

    # Phase 4: score the run against the observations sitting beside it. Last,
    # because it reads the series the two phases above just wrote.
    from hydromodpy.simulation.extraction.derivation.fit_metrics import write_fit_metrics

    try:
        write_fit_metrics(sim_id, store)
    except Exception:
        # A run's own results are already in; a missing score must not lose them.
        logger.warning("Could not score the run against its observations", exc_info=True)


def sample_declared_observation_points(*, ctx: RunContext, sim_id: str, store: Any) -> int:
    """Sample the ``[observation]`` points while the run still holds its fields.

    A point known in advance costs nothing to read later: its series lands in
    the run timeseries payload and its declaration in the run directory. A
    failure here is logged, never fatal: the run's own results are already in.
    """
    observation = getattr(ctx.state.cfg, "observation", None)
    declarations = observation.declarations() if observation is not None else []
    if not declarations:
        return 0
    try:
        return int(store.sample_observation_points(sim_id, declarations))
    except Exception:
        logger.warning("Could not sample the declared observation points", exc_info=True)
        return 0


def is_run_request(request: ExportRequest) -> bool:
    """Return whether a request writes the whole run: the package or a metadata view.

    Those read the seal, so they run after it; every other request runs before.
    """
    return request.output_format in RUN_FORMATS


def auto_export_results(
    *,
    sim_id: str,
    store: Any,
    export_requests: Sequence[ExportRequest],
    save_catalog: bool,
    run_id: str | None = None,
) -> list[Path]:
    """Write the ``[[export]]`` requests of one run that read its data, not its seal.

    Files land in ``share/<run>/`` unless a request names a folder or a file.
    Returns the files written; :func:`announce_exports` says it on the console.
    """
    if not save_catalog:
        return []
    requests = [request for request in export_requests if not is_run_request(request)]
    return _auto_export(sim_id, store, requests, label=run_id or sim_id[:8])


def auto_export_package(
    *,
    sim_id: str,
    store: Any,
    export_requests: Sequence[ExportRequest],
    save_catalog: bool,
    run_id: str | None = None,
) -> list[Path]:
    """Write the package and metadata requests of one run.

    Called on a *sealed* run, while the store is still open: the archive
    bundles the run seal (manifest, provenance, frozen config), the views
    render it, and the packer still needs the index and the live Zarr
    directory. Returns the files written.
    """
    if not save_catalog:
        return []
    requests = [request for request in export_requests if is_run_request(request)]
    return _auto_export(sim_id, store, requests, label=run_id or sim_id[:8])


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


def _auto_export(
    sim_id: str,
    store: Any,
    requests: Sequence[ExportRequest],
    *,
    label: str,
) -> list[Path]:
    """Write each request in the order of the file and say once where they went.

    A request that fails does not stop the next one; the failures are raised
    together once every request had its turn. Exports are written to
    ``share/<label>/`` so the published tree is organized by run name, not
    UUID.
    """
    if not requests:
        return []
    output_dir = share_dir_for(store.project_path) / label
    failures: list[str] = []
    written: list[Path] = []
    for index, request in enumerate(requests):
        try:
            written.extend(store.export(sim_id, request, default_folder=output_dir))
        except Exception as exc:
            failures.append(f"export request {index + 1} ({_describe(request)}): {exc}")

    if any(path.parent == output_dir for path in written):
        _write_run_card(output_dir, sim_id, label)
    if failures:
        raise RuntimeError(f"Auto-export failed for sim {sim_id}: " + "; ".join(failures))
    return written


def announce_exports(written: Sequence[Path], output_dir: Path) -> None:
    """Say on the console how many files the exports of a run wrote, and where.

    The exporters name every file they write, one INFO line each. This is the
    one line the default verbosity keeps, printed once for the whole run.
    """
    if written:
        logger.info(
            "Exported %d file(s) -> %s",
            len(written),
            display_path(output_dir),
            extra=MILESTONE,
        )


def _describe(request: ExportRequest) -> str:
    """Name a request in an error: its variables and its format."""
    names = request.variables if isinstance(request.variables, str) else ", ".join(request.names)
    fmt = request.output_format
    return f"variables = {names}" + (f", format = {fmt.value}" if fmt is not None else "")


def _write_run_card(output_dir: Path, sim_id: str, label: str) -> None:
    """Write a small RUN.txt so a copied export folder stays self-identifying."""
    try:
        (output_dir / "RUN.txt").write_text(
            f"name: {label}\nid: {sim_id[:8]}\nsim_id: {sim_id}\n", encoding="utf-8"
        )
    except OSError:
        pass
