"""Post-run hook that ingests solver outputs into the store of the run.

Called by ``SimulationRunner`` after each solver execution completes.
Orchestrates the results lifecycle of a run: extract, derive, cleanup,
provenance. The exports are the export step of the workflow.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

from hydromodpy.core.budget.flux import networks_route_drainage
from hydromodpy.core.budget.terms import BudgetKeep
from hydromodpy.core.exceptions import SolverInputError
from hydromodpy.core.logging import get_logger
from hydromodpy.model.forcing.recharge_rates import CRITERION_MEAN_RECHARGE_ATTR, mean_recharge_m_s
from hydromodpy.model.sinks_sources.wells import (
    WELL_THROTTLE_WARNING_FRACTION,
    WELLS_PUMPED_CHECK,
    WELLS_PUMPED_METRIC,
)
from hydromodpy.solver.base.plan import RunContext, RunExecutionResult
from hydromodpy.solver.base.registry import extractors, solvers
from hydromodpy.solver.base.results_config import ResultsConfig

logger = get_logger(__name__)


class OutputAdapter(Protocol):
    """The solver extractor port: it reads the solver files of a run into its store.

    ``extract_run_outputs`` also passes ``budget_terms``, ``start_datetime``,
    ``vertical_layout`` and the dry-cell sentinels, each only when ``extract``
    declares that keyword.
    """

    def extract(
        self,
        sim_id: str,
        solver_output_dir: Path,
        store: Any,
    ) -> None: ...


def record_run_execution_metrics(
    *,
    ctx: RunContext,
    sim_id: str,
    store: Any,
    result: RunExecutionResult,
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


def post_run_results(
    *,
    ctx: RunContext,
    sim_id: str,
    results_config: ResultsConfig,
    store: Any,
    keep_solver_files: bool | None = None,
    budget_terms: BudgetKeep | None = None,
) -> None:
    """Ingest solver outputs into the store of the run after it completes.

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
    store : RunStore
        The open store of the run.
    budget_terms : BudgetKeep, optional
        The per-cell budget the plan of the run keeps. A direct call without
        a plan keeps every term, which ``keep_per_cell_budget = true`` (the
        default) asks for; with ``false`` the plan's terms must be passed.
    """
    if not ctx.run.is_solver_backed:
        return
    if not results_config.persistence.save_catalog:
        return
    if budget_terms is None:
        if not results_config.keep_per_cell_budget:
            raise ValueError(
                "[simulation.results] keep_per_cell_budget = false keeps the terms the "
                "consumers of the run read, which only its plan knows: pass budget_terms."
            )
        budget_terms = BudgetKeep.everything()

    extract_run_outputs(
        ctx=ctx,
        sim_id=sim_id,
        results_config=results_config,
        store=store,
        budget_terms=budget_terms,
    )
    derive_run_outputs(
        ctx=ctx,
        sim_id=sim_id,
        results_config=results_config,
        store=store,
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
    budget_terms: BudgetKeep,
) -> None:
    """Extract raw solver outputs into the Catalog.

    ``budget_terms`` is the per-cell budget the run keeps; an extractor that
    writes one takes it as its ``budget_terms`` keyword.
    """
    if not ctx.run.is_solver_backed:
        return
    if not results_config.persistence.save_catalog:
        return

    solver_name = ctx.run.solver
    solver_output_dir = ctx.output_dir

    try:
        extractor = extractors.create(ctx.run.process_type, solver_name)
    except SolverInputError as exc:
        raise RuntimeError(
            f"No output adapter registered for {ctx.run.process_type}/{solver_name}"
        ) from exc

    # Phase 1: extract raw outputs
    if solver_output_dir is None or not solver_output_dir.exists():
        raise FileNotFoundError(
            f"Solver output directory is missing for sim {sim_id}: {solver_output_dir}"
        )

    extract_kwargs: dict[str, Any] = {}
    if _accepts_kwarg(extractor.extract, "budget_terms"):
        extract_kwargs["budget_terms"] = budget_terms
    start_datetime = _resolve_run_start_datetime(ctx)
    if start_datetime is not None and _accepts_kwarg(extractor.extract, "start_datetime"):
        extract_kwargs["start_datetime"] = start_datetime
    for keyword, value in _dry_cell_sentinels(ctx).items():
        if _accepts_kwarg(extractor.extract, keyword):
            extract_kwargs[keyword] = value
    if _accepts_kwarg(extractor.extract, "vertical_layout"):
        extract_kwargs["vertical_layout"] = ctx.state.cfg.domain.layers.vertical_layout
    extractor.extract(sim_id, solver_output_dir, store, **extract_kwargs)

    _keep_the_criterion_recharge(ctx=ctx, sim_id=sim_id, store=store)
    _finalize_run_provenance(ctx=ctx, sim_id=sim_id, store=store)


def record_what_the_model_says(*, ctx: RunContext, sim_id: str, store: Any) -> None:
    """Write what only the built model knows: its mean recharge, its grid, its binary.

    The solver step calls this as soon as the solve ends, because a run resumed
    from its extract step has no model in memory. A run whose extractor creates the
    field store gets the recharge from the extraction, as before.
    """
    if store.fields_path.exists():
        _keep_the_criterion_recharge(ctx=ctx, sim_id=sim_id, store=store)
    _finalize_run_provenance(ctx=ctx, sim_id=sim_id, store=store)


def _keep_the_criterion_recharge(*, ctx: RunContext, sim_id: str, store: Any) -> None:
    """Keep on the run the mean recharge its trials read, for a later redraw to read back."""
    model = ctx.model
    if getattr(model, "recharge", None) is None:
        return
    try:
        mean_recharge = mean_recharge_m_s(model)
    except ValueError:
        logger.debug("The model of sim %s holds no finite recharge rate.", sim_id)
        return
    fields = store.open_zarr(sim_id)
    try:
        fields.write_forcing_attrs({CRITERION_MEAN_RECHARGE_ATTR: mean_recharge})
    finally:
        fields.close()


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


def _dry_cell_sentinels(ctx: RunContext) -> dict[str, float]:
    """Return the head sentinels the solver was configured to write.

    MODFLOW-NWT stamps dry cells with ``[solver.modflow_nwt.runtime.upw] hdry`` and
    inactive cells with ``[solver.modflow_nwt.runtime.bas] hnoflo``; the extractor
    masks exactly those values to NaN. Reading them back from defaults would
    keep -100 and -9999 in the heads of anyone who changed them.
    """
    runtime = ctx.state.cfg.solver.options_of("modflow_nwt").runtime
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


def _drainage_outside_routed(ctx: RunContext) -> bool:
    """True when no network routes the hillslope drainage, a lake alone included."""
    setup = getattr(getattr(ctx, "state", None), "setup", None)
    return not networks_route_drainage(getattr(setup, "model", None))


def derive_run_outputs(
    *,
    ctx: RunContext,
    sim_id: str,
    results_config: ResultsConfig,
    store: Any,
) -> None:
    """Write what the run derives once its fields are in the store.

    The discharge band of the drains and the catchment aggregates. Derived
    fields are not written: every one is rebuilt on read. The declared
    observation points and the score are the derive step of the workflow.
    """
    if not ctx.run.is_solver_backed:
        return
    if not results_config.persistence.save_catalog:
        return

    solver_name = ctx.run.solver
    try:
        extractors.get(ctx.run.process_type, solver_name)
        category = solvers.get(ctx.run.process_type, solver_name).category
    except SolverInputError as exc:
        raise RuntimeError(
            f"No output adapter registered for {ctx.run.process_type}/{solver_name}"
        ) from exc

    # The discharge band the drains were given changes what "this cell seeps"
    # means, so it has to stay in the store for every seepage mask read and
    # every figure drawn afterwards. Written here rather than in the workflow
    # step because this function is the one funnel both the step and the
    # direct post-run path go through.
    sim_zarr = store.open_zarr(sim_id)
    try:
        sim_zarr.drain_band_depth_m = float(ctx.state.cfg.solver.drain_band_depth_m)
    finally:
        sim_zarr.close()

    # Aggregate catchment timeseries from spatial fields
    if category != "lumped":
        from hydromodpy.results.derive.catchment_aggregation import aggregate_catchment_timeseries

        aggregate_catchment_timeseries(
            sim_id, store, drainage_outside_routed=_drainage_outside_routed(ctx)
        )


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
