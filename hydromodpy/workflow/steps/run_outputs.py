"""What happens to the solver outputs of a run once it is solved.

The extract, derive, export and run-solver steps of the workflow call these
functions, each on the ``RunContext`` of one run, whose ``solver_run`` is what
the runner recorded for it. They orchestrate the results lifecycle of a run:
extract through the adapter of its backend, derive, cleanup, provenance. The
exports are the export step of the workflow.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from hydromodpy.catchment.preprocess.delineated_catchment import catchment_outline
from hydromodpy.catchment.stream_network.geometry import open_water_mask
from hydromodpy.core.budget.flux import networks_route_drainage
from hydromodpy.core.exceptions import ConfigError, NothingThereError, SolverInputError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.time.period_aggregation import naive_timestamp, period_edges
from hydromodpy.mesh.planar.geometry import cell_polygons, padded_rows
from hydromodpy.model.forcing.recharge_rates import CRITERION_MEAN_RECHARGE_ATTR
from hydromodpy.model.sinks_sources.wells import (
    WELL_THROTTLE_WARNING_FRACTION,
    WELLS_PUMPED_CHECK,
    WELLS_PUMPED_METRIC,
)
from hydromodpy.results.derive.stream_network.criterion_inputs import (
    catchment_cells,
    criterion_recharge_of_run,
    declared_crs,
)
from hydromodpy.results.storage.declared import refuse_undeclared, stored_names
from hydromodpy.results.storage.kept import Retention
from hydromodpy.solver.base.plan import RunContext, SolverRun
from hydromodpy.solver.base.registry import solvers

logger = get_logger(__name__)


def record_run_execution_metrics(
    *,
    ctx: RunContext,
    sim_id: str,
    store: Any,
    result: SolverRun,
) -> None:
    """Persist lightweight solver-side execution metrics in the facts of the run.

    The store keeps them apart from the scores: the index and the readers of scores leave them out.
    """
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
        store.write_runtime_metric(
            sim_id,
            station_id=str(ctx.run.id),
            metric_name=str(metric_name),
            value=value,
        )
    _check_wells_pumped(store, metrics)


def _check_wells_pumped(store: Any, metrics: Mapping[str, Any]) -> None:
    """Put the wells-pumped verdict in the checks of the run, when the run has wells.

    The solver publishes only the volume it applied. A cut of more than the
    share a cut is reported at fails the verdict, which stays non-fatal: the run
    is sound, it only pumped less than it was told to.
    """
    raw = metrics.get(WELLS_PUMPED_METRIC)
    facts = getattr(store, "facts", None)
    if raw is None or facts is None:
        return
    try:
        pumped = float(raw)
    except (TypeError, ValueError):
        return
    if not math.isfinite(pumped):
        return
    passed = pumped >= 100.0 * (1.0 - WELL_THROTTLE_WARNING_FRACTION)
    message = (
        f"the wells pumped {pumped:.0f} % of the requested volume"
        if passed
        else (
            f"the wells pumped {pumped:.0f} % of the requested volume: MODFLOW 6 "
            "AUTO_FLOW_REDUCE cut the pumping of nearly dry cells. Put the well in a "
            "deeper layer or lower its rate."
        )
    )
    facts.note_validity(WELLS_PUMPED_CHECK, passed, pumped, message)


def extract_run_outputs(*, ctx: RunContext, store: Any, retention: Retention) -> None:
    """Extract the raw solver outputs of ``ctx.solver_run`` into the store of the run.

    The adapter of the backend reads what it needs on the ``SolverRun``: its
    output folder, its ``Model`` and its options. ``retention`` says which
    per-cell budget terms the run keeps. A run with no output folder on disk
    raises ``NothingThereError``. A field or a table the extractor adds outside
    ``writes`` of its backend raises ``DataContractViolation``.
    """
    if not ctx.run.is_solver_backed:
        return

    solver_run = ctx.solver_run
    output_dir = None if solver_run is None else solver_run.output_dir
    if output_dir is None or not output_dir.exists():
        raise NothingThereError(
            f"Solver output directory is missing for sim {store.sim_id}: {output_dir}"
        )

    adapter = solvers.create(ctx.run.process_type, ctx.run.solver)
    before = stored_names(store.run_dir)
    adapter.extract(solver_run, store, retention)
    refuse_undeclared(stored_names(store.run_dir) - before, adapter.writes, backend=ctx.run.solver)

    _keep_what_the_criterion_reads(ctx=ctx, sim_id=store.sim_id, store=store)
    _finalize_run_provenance(solver_run=solver_run, sim_id=store.sim_id, store=store)


def record_what_the_model_says(*, ctx: RunContext, sim_id: str, store: Any) -> None:
    """Write what only the built solver model knows: what the criterion reads, its grid, its binary.

    The solver step calls this as soon as the solve ends, because a run resumed
    from its extract step has no solver model in memory. A run whose extractor
    creates the field store gets what the criterion reads from the extraction.
    """
    _keep_what_the_criterion_reads(ctx=ctx, sim_id=sim_id, store=store)
    _finalize_run_provenance(solver_run=ctx.solver_run, sim_id=sim_id, store=store)


def _keep_what_the_criterion_reads(*, ctx: RunContext, sim_id: str, store: Any) -> None:
    """Keep on the run what the stream criterion read, for a later redraw to read back.

    That is the mean recharge its seepage threshold is a fraction of, the cells of
    open water that leave its supports, and the cells inside the catchment
    outline. Each comes from the one function a trial calls
    (:mod:`hydromodpy.results.derive.stream_network.criterion_inputs`), so a figure scores
    the cells the trials scored. Only the flow run keeps them, because the
    trials read its heads and its recharge. A transport run of the same
    simulation would write the stored forcing over the rate the flow model held.
    A run that keeps no field store gets none here.
    """
    if ctx.run.process_type != "flow":
        return
    solver_run = ctx.solver_run
    model = None if solver_run is None else solver_run.solver_model
    if model is None or not store.save_zarr or not store.fields_path.exists():
        return
    fields = store.open_zarr(sim_id)
    try:
        recharge = criterion_recharge_of_run(model, fields, _period_edges(store, fields))
        if recharge is None:
            logger.debug("Sim %s: no source gives the criterion a mean recharge.", sim_id)
        else:
            fields.write_forcing_attrs({CRITERION_MEAN_RECHARGE_ATTR: recharge})
        _keep_the_cells_the_criterion_reads(ctx, model, fields)
    finally:
        fields.close()


def _period_edges(store: Any, fields: Any) -> Any:
    """Return the ``n + 1`` period edges of the run, or ``None`` when it carries no dates."""
    stamps = fields.read_time()
    if stamps is None:
        return None
    start = getattr(getattr(store, "facts", None), "period_start", None)
    try:
        return period_edges(stamps, start=None if start is None else naive_timestamp(start))
    except ValueError:
        return None


def _keep_the_cells_the_criterion_reads(ctx: RunContext, model: Any, fields: Any) -> None:
    """Write ``mesh/open_water`` and, when an outline exists, ``mesh/catchment_cells``."""
    import numpy as np

    mesh = getattr(model, "solver_mesh", None)
    planar = getattr(mesh, "planar_mesh", None)
    if mesh is None or planar is None:
        return
    n_cells = int(mesh.n_cells)
    water = open_water_mask(getattr(model, "open_water_cell_ids", None), n_cells)
    setup = ctx.state.setup
    geographic = getattr(setup, "geographic", None)
    outline = catchment_outline(geographic, getattr(setup, "cell_mesh", None))
    cells = None
    if outline is not None:
        vertices = np.asarray(planar.vertices, dtype=float)
        connectivity = padded_rows(planar.flat_connectivity, n_nodes=len(vertices))
        cells = catchment_cells(
            cell_polygons(vertices, connectivity), outline, mesh_crs=declared_crs(geographic)
        )
    fields.write_criterion_cells(
        open_water=np.zeros(n_cells, dtype=bool) if water is None else water,
        catchment_cells=cells,
    )


def _finalize_run_provenance(*, solver_run: SolverRun | None, sim_id: str, store: Any) -> None:
    """Backfill provenance known only after the solver grid is built and run.

    The simulation row is registered before the solver grid exists (NULL grid
    metadata for DISV-from-raster runs), and the recorded binary is a best guess;
    both are refined here from the solver model the run actually produced.
    """
    model = None if solver_run is None else solver_run.solver_model
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
    except (AttributeError, TypeError, ValueError):
        logger.debug("run grid: no %s on this solver mesh", "mesh topology", exc_info=True)
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
    except (AttributeError, TypeError, ValueError):
        logger.debug("run grid: no %s on this solver mesh", "bounding box", exc_info=True)
    try:
        vertices = np.asarray(planar.vertices, dtype=float)
        conn = np.asarray(planar.flat_connectivity, dtype=np.int64)
        # The node ids of each cell in turn, without the -1 padding of a polygon row.
        conn_bytes = conn[conn >= 0].tobytes()
        meta["mesh_hash"] = hashlib.sha256(vertices.tobytes() + conn_bytes).hexdigest()
    except (AttributeError, TypeError, ValueError):
        logger.debug("run grid: no %s on this solver mesh", "mesh hash", exc_info=True)
    return meta


def _drainage_outside_routed(solver_run: SolverRun) -> bool:
    """True when no network routes the hillslope drainage, a lake alone included."""
    return not networks_route_drainage(solver_run.model)


def derive_run_outputs(*, ctx: RunContext, store: Any) -> None:
    """Write what the run derives once its fields are in the store.

    The discharge band of the drains and the catchment aggregates. Derived
    fields are not written: every one is rebuilt on read. The declared
    observation points and the score are the derive step of the workflow. The
    ``Model`` of ``ctx.solver_run`` gives the band depth and the networks; the
    solver model is not read, so a run whose solver model was released derives
    as before.
    """
    if not ctx.run.is_solver_backed:
        return

    solver_run = ctx.solver_run
    if solver_run is None or solver_run.model is None:
        raise ConfigError(
            f"Run '{ctx.run.id}' has no Model to derive from: its solver run was not recorded."
        )
    category = solvers.get(ctx.run.process_type, ctx.run.solver).category

    # The discharge band the drains were given changes what "this cell seeps"
    # means, so it has to stay in the store for every seepage mask read and
    # every figure drawn afterwards.
    sim_zarr = store.open_zarr(store.sim_id)
    try:
        sim_zarr.drain_band_depth_m = float(solver_run.model.options.drain_band_depth_m)
    finally:
        sim_zarr.close()

    # Aggregate catchment timeseries from spatial fields
    if category != "lumped":
        from hydromodpy.results.derive.catchment_aggregation import aggregate_catchment_timeseries

        aggregate_catchment_timeseries(
            store.sim_id, store, drainage_outside_routed=_drainage_outside_routed(solver_run)
        )


def cleanup_solver_outputs(*, ctx: RunContext, retention: Retention) -> None:
    """Cleanup raw solver files through the matching solver adapter, unless the run keeps them."""
    if not ctx.run.is_solver_backed or ctx.solver_run is None:
        return
    if retention.solver_files:
        return
    try:
        adapter = solvers.create(ctx.run.process_type, ctx.run.solver)
    except SolverInputError:
        logger.debug(
            "No solver adapter registered for %s/%s, skipping cleanup",
            ctx.run.process_type,
            ctx.run.solver,
        )
        return
    try:
        adapter.cleanup(ctx.solver_run)
    except Exception:
        logger.warning("Failed to cleanup solver files for run %s", ctx.run.id, exc_info=True)
