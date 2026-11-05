"""Concern 3 of PrepareSolverStep: opening the run and freezing what it was built from.

Hosts the helpers that bind the pipeline to its run directory (the claim
the caller made, or the one this step makes), write the facts the seal
needs into the run store, freeze the resolved configuration and the CRS and
time axis of the field store. Every write goes through a store its caller
owns and closes; none of them opens one, and none reads a handle off the
context.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from hydromodpy.core.exceptions import PipelineError
from hydromodpy.core.logging import get_logger
from hydromodpy.results.catalog.constants import solver_category
from hydromodpy.results.catalog.registration import (
    portable_config_source,
    solve_identity_hash,
    split_stem_version,
)
from hydromodpy.results.lineage import Lineage
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import claim_reserved_directory, claim_run_directory
from hydromodpy.results.storage.run_facts import RunFacts, read_facts
from hydromodpy.workflow.steps.prepare_solver.facts import (
    collect_run_facts,
    primary_solver_for_simulation,
)
from hydromodpy.workflow.steps.prepare_solver.freeze import freeze_run_config
from hydromodpy.workflow.steps.prepare_solver.prepare import (
    step_persist_geographic,
    step_persist_mesh,
    step_persist_params,
)
from hydromodpy.workflow.steps.prepare_solver.restart import resolve_restart_source

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.storage.run_store import RunStore
    from hydromodpy.solver.modflow_common.binaries import SolverEngine

logger = get_logger(__name__)


def _execution_mode(ctx: WorkflowContext, solver_name: str | None) -> str:
    """Return the solve dispatch this run uses: 'subprocess' or 'api'.

    Only MODFLOW 6 offers a second dispatch (``libmf6`` through the BMI
    wrappers); every other backend runs its executable.

    The declared ``mf6_runner`` is the fallback, not the answer: the build
    forces the in-process runner whenever a lake carries exposed-band
    (marnage) runoff, so a configuration that says ``subprocess`` can still
    solve through the shared library. Once the model exists, it - not the
    configuration - states the dispatch.
    """
    if str(solver_name or "") != "modflow6":
        return "subprocess"
    executed = _built_model_runner(ctx, solver_name)
    if executed is not None:
        return executed
    runtime = getattr(getattr(ctx.cfg, "modflow6", None), "runtime", None)
    return "api" if getattr(runtime, "mf6_runner", "subprocess") == "api" else "subprocess"


def _built_model_runner(ctx: WorkflowContext, solver_name: str) -> str | None:
    """Return the dispatch of the built flow model, or None before it exists."""
    from hydromodpy.solver.modflow_common.flow_adapter_helpers import resolve_modflow_runner

    execution = getattr(ctx, "execution", None)
    plan = getattr(execution, "simulation_plan", None)
    models = getattr(execution, "models_by_run_id", None) or {}
    if plan is None or not models:
        return None
    for run in getattr(plan, "runs", ()) or ():
        is_primary_flow = (
            getattr(run, "process_type", None) == "flow"
            and getattr(run, "solver", None) == solver_name
        )
        if not is_primary_flow:
            continue
        model = models.get(getattr(run, "id", None))
        if model is not None:
            return resolve_modflow_runner(model)
    return None


def _resolve_solver_engine(ctx: WorkflowContext, solver_name: str | None) -> SolverEngine | None:
    """Resolve the engine this run executes, or None when it has no binary."""
    from hydromodpy.solver.modflow_common.binaries import resolve_solver_engine

    workspace = getattr(ctx.setup, "workspace", None)
    return resolve_solver_engine(
        str(solver_name or ""),
        execution_mode=_execution_mode(ctx, solver_name),
        bin_path=getattr(workspace, "bin_path", None),
    )


def _solver_options_of_the_built_model(
    ctx: WorkflowContext, solver_name: str | None
) -> dict | None:
    """Return what the built flow model decided for its solver, or None before it exists."""
    plan = ctx.execution.simulation_plan
    models = ctx.execution.models_by_run_id
    for run in getattr(plan, "runs", ()) or ():
        if run.process_type == "flow" and run.solver == solver_name and run.id in models:
            read_back = getattr(models[run.id], "resolved_solver_options", None)
            return None if read_back is None else read_back()
    return None


def _write_run_environment(
    ctx: WorkflowContext,
    sim_id: str,
    solver_name: str | None,
    *,
    store: RunStore,
) -> None:
    """Record the host environment plus the engine identity of the run."""
    engine = _resolve_solver_engine(ctx, solver_name)
    store.write_run_environment(
        sim_id,
        project_root=getattr(getattr(ctx.setup, "workspace", None), "project_root", None),
        solver_name=solver_name,
        solver_binary_path=None if engine is None else engine.path,
        solver_engine=None if engine is None else engine.kind,
        solver_execution_mode=_execution_mode(ctx, solver_name),
        solver_version_text=None if engine is None else engine.version,
        solver_options=_solver_options_of_the_built_model(ctx, solver_name),
        rng_seed=getattr(ctx.cfg.simulation, "rng_seed", None),
    )


def refresh_run_environment(ctx: WorkflowContext, *, store: RunStore) -> None:
    """Rewrite the engine identity of a run once its model has been solved.

    The run opens before the model exists, so the facts can only name the
    engine the configuration asked for. This second pass reads the dispatch
    off the built model and overwrites them, so ``provenance.json`` names the
    executable or the shared library that really ran.
    """
    sim_id = getattr(ctx, "sim_id", None)
    plan = getattr(getattr(ctx, "execution", None), "simulation_plan", None)
    if not sim_id or plan is None:
        return
    try:
        _write_run_environment(ctx, str(sim_id), primary_solver_for_simulation(plan), store=store)
    except Exception:
        logger.exception("Failed to refresh the run environment for sim %s", str(sim_id)[:8])


def _crs_grid_mapping_attrs(crs: object) -> dict[str, object]:
    """Return CF grid-mapping attrs for a CRS value."""
    try:
        from pyproj import CRS

        parsed = CRS.from_user_input(crs)
        attrs = dict(parsed.to_cf())
        if "crs_wkt" not in attrs:
            attrs["crs_wkt"] = parsed.to_wkt()
        epsg = parsed.to_epsg()
        if epsg is not None:
            attrs["epsg_code"] = int(epsg)
        return attrs
    except Exception:
        return {"crs_wkt": str(crs)}


def _write_zarr_crs(ctx: WorkflowContext, sim_id: str, *, store: RunStore) -> None:
    """Persist CRS metadata in the field store when configured."""
    geographic_cfg = getattr(ctx.cfg, "geographic", None)
    crs = getattr(geographic_cfg, "crs_project", None)
    if crs is None:
        return
    attrs = _crs_grid_mapping_attrs(crs)
    epsg_raw = attrs.get("epsg_code")
    semi_major_raw = attrs.get("semi_major_axis")
    inverse_flattening_raw = attrs.get("inverse_flattening")
    store.write_crs(
        sim_id,
        crs_wkt=str(attrs.get("crs_wkt", str(crs))),
        grid_mapping_name=str(attrs.get("grid_mapping_name", "latitude_longitude")),
        epsg_code=int(str(epsg_raw).strip()) if epsg_raw is not None else None,
        semi_major_axis=float(str(semi_major_raw).strip()) if semi_major_raw is not None else None,
        inverse_flattening=(
            float(str(inverse_flattening_raw).strip())
            if inverse_flattening_raw is not None
            else None
        ),
    )


def _write_zarr_time(ctx: WorkflowContext, sim_id: str, *, store: RunStore) -> None:
    """Persist simulation period-end timestamps as CF time coordinates."""
    time_grid = getattr(ctx.setup, "time_grid", None)
    boundaries = getattr(time_grid, "boundaries", None)
    import numpy as np
    import pandas as pd

    if boundaries and len(boundaries) >= 2:
        period_ends = pd.DatetimeIndex(boundaries[1:])
    else:
        datetimes = getattr(time_grid, "datetimes", None)
        if not datetimes:
            return
        period_ends = pd.DatetimeIndex(datetimes)
    if period_ends.tz is None:
        period_ends = period_ends.tz_localize("UTC")
    else:
        period_ends = period_ends.tz_convert("UTC")
    epoch = pd.Timestamp("1970-01-01T00:00:00Z")
    seconds = ((period_ends - epoch).total_seconds()).astype("int64")
    store.write_time(
        sim_id,
        np.asarray(seconds, dtype="int64"),
        epoch="1970-01-01T00:00:00Z",
        units="seconds since 1970-01-01T00:00:00Z",
    )


def bind_restart_source(ctx: WorkflowContext, *, store: RunStore) -> str | None:
    """Resolve ``[flow] restart_from`` to the store it names and link the run to it.

    The reference (a run name, a ``sim_id`` or a path) becomes the path the
    solver builder reads, so the frozen configuration writes it relative to
    the project, and the lineage of the run names the ``sim_id`` of the
    source. The identity hash of the run was taken on the reference before
    this call, so the same reference hashes the same on every machine.
    Returns the ``sim_id`` of the source, which the frozen configuration
    writes beside its path.
    """
    flow_cfg = getattr(ctx.cfg, "flow", None)
    reference = getattr(flow_cfg, "restart_from", None)
    if not reference:
        return None
    project_root = Path(store.workspace_path or store.run_dir.parent.parent)
    source = resolve_restart_source(project_root, reference)
    flow_cfg.restart_from = str(source.path)
    lineage = store.facts.lineage
    if source.sim_id is not None and lineage.parent_sim_id is None:
        store.facts.lineage = lineage.model_copy(
            update={"parent_sim_id": source.sim_id, "parent_hint": source.rel_dir}
        )
        ctx.lineage = store.facts.lineage
    return source.sim_id


def register_tracked_input_files(ctx: WorkflowContext, *, store: RunStore) -> None:
    """Walk the config tree and record every InputFile-marked path."""
    from hydromodpy.core.tracking import collect_input_files

    # Anchor relative paths on the project, not on the shell's working
    # directory: a bare filename is resolved under <workspace>/data/<family>/
    # everywhere else, and tracking it from the cwd silently dropped it.
    project_root = getattr(getattr(ctx.setup, "workspace", None), "project_root", None)
    try:
        entries = collect_input_files(ctx.cfg, base=project_root)
    except Exception as exc:
        logger.warning("Skipping tracked-file registration: %s", exc)
        return

    portable = [e for e in entries if e.portable]
    if not portable:
        return
    written = store.register_tracked_files(ctx.sim_id, portable)
    logger.debug("Recorded %d tracked input file(s) for simulation %s", written, ctx.sim_id)


def bind_run_directory(
    ctx: WorkflowContext,
    *,
    run_dir: Path | None,
    lineage: Lineage | None,
    calibrated_by: Any,
    run_overrides: dict | None,
) -> Path:
    """Bind the context to the run directory of this attempt and return it.

    ``run_dir`` is the directory the caller claimed or reserved. Without
    one, the step claims the directory of the case named by the context. A
    reserved directory that carries no outcome yet (a promotion) receives
    its first outcome here. The identity of the attempt is read back from
    the outcome, so one claim serves every step.
    """
    workspace = ctx.setup.workspace
    if workspace is None:
        raise PipelineError("Workspace is required before opening a run.")
    project_root = Path(workspace.project_root)
    case = str(ctx.setup.run_id)
    site = getattr(getattr(ctx.cfg, "site", None), "name", None)
    target = Path(run_dir) if run_dir is not None else getattr(ctx, "run_dir", None)
    if target is None:
        claim = claim_run_directory(
            project_root, case, case_id=case, project=project_root.name, site=site
        )
        target = claim.run_dir
    outcome = read_outcome(target)
    if outcome is None:
        reserved = ctx.reserved_sim_id
        claim_reserved_directory(
            target,
            case_id=split_stem_version(target.name)[0],
            project=project_root.name,
            site=site,
            sim_id=reserved,
        )
        outcome = read_outcome(target)
        assert outcome is not None
    ctx.reserved_sim_id = None
    ctx.run_dir = target
    ctx.sim_id = outcome.sim_id
    ctx.attempt = outcome.attempt
    if lineage is not None:
        ctx.lineage = lineage
    elif ctx.lineage is None:
        ctx.lineage = Lineage(
            parent_sim_id=ctx.parent_sim_id,
            kind="rerun" if ctx.parent_sim_id is not None else None,
            overrides=dict(run_overrides or {}),
        )
    if calibrated_by is not None:
        ctx.calibrated_by = calibrated_by
    return target


def planned_recipe(project_root: Path, case_id: str) -> str | None:
    """Return the recipe of *case_id* in the current plan, or None outside a plan.

    A case id names its site and its recipe for the life of the project, so
    the current plan answers for a case of any earlier plan too.
    """
    from hydromodpy.results.plan_store import read_plan
    from hydromodpy.results.storage.json_io import readable

    stored = readable(read_plan, project_root)
    if stored is None:
        return None
    case = next((case for case in stored.cases if case.case_id == case_id), None)
    return None if case is None else case.recipe


def initial_facts(ctx: WorkflowContext, *, config_hash: str | None = None) -> RunFacts:
    """Return the facts of the attempt as the context knows them at opening.

    *config_hash* is the identity hash the caller computed for the claim; it
    is computed here from the configuration when the caller has none.
    """
    workspace = ctx.setup.workspace
    assert workspace is not None and ctx.run_dir is not None and ctx.sim_id is not None
    project_root = Path(workspace.project_root)
    outcome = read_outcome(ctx.run_dir)
    assert outcome is not None
    stored = read_facts(ctx.run_dir)
    plan = ctx.execution.simulation_plan
    primary_solver = primary_solver_for_simulation(plan)
    facts = collect_run_facts(ctx)
    facts["config_hash"] = config_hash or solve_identity_hash(ctx.cfg)
    facts["config_source"] = portable_config_source(project_root, facts.get("config_source"))
    return RunFacts(
        sim_id=ctx.sim_id,
        name=ctx.run_dir.name,
        case_id=outcome.case_id,
        recipe=planned_recipe(project_root, outcome.case_id),
        project=outcome.project or project_root.name,
        attempt=outcome.attempt,
        attempt_id=outcome.attempt_id,
        created_at=stored.created_at if stored is not None else outcome.started_at,
        started_at=outcome.started_at,
        solver=primary_solver,
        solver_category=solver_category(primary_solver),
        lineage=ctx.lineage if ctx.lineage is not None else Lineage(),
        calibrated_by=ctx.calibrated_by,
        **facts,
    )


def step_open_run(ctx: WorkflowContext, *, store: RunStore) -> None:
    """Record what the run was built from in its store.

    The store is the one of ``ctx.run_dir``, opened by the caller on the
    facts :func:`initial_facts` built.
    """
    assert ctx.sim_id is not None
    plan = ctx.execution.simulation_plan
    primary_solver = primary_solver_for_simulation(plan)
    facts = store.facts
    cell_mesh = ctx.setup.cell_mesh
    if cell_mesh is not None and facts.n_layers is not None and not store.fields_path.exists():
        store.create_zarr(
            n_cells=int(cell_mesh.n_cells),
            n_layers=int(facts.n_layers),
            cell_types=[cell_mesh.mesh.single_cell_type.value],
        )
    restart_sim_id = bind_restart_source(ctx, store=store)
    freeze_run_config(ctx, store=store, restart_sim_id=restart_sim_id)
    _write_zarr_time(ctx, ctx.sim_id, store=store)
    _write_zarr_crs(ctx, ctx.sim_id, store=store)

    try:
        _write_run_environment(ctx, ctx.sim_id, primary_solver, store=store)
    except Exception:
        logger.exception("Failed to capture run environment for sim %s", ctx.sim_id[:8])

    register_tracked_input_files(ctx, store=store)

    if ctx.setup.flow is not None:
        step_persist_params(
            store,
            ctx.sim_id,
            ctx.setup.flow,
            domain=ctx.setup.domain,
        )

    step_persist_mesh(ctx, ctx.sim_id, store=store)
    step_persist_geographic(ctx, ctx.sim_id, store=store)


__all__ = (
    "bind_run_directory",
    "initial_facts",
    "planned_recipe",
    "refresh_run_environment",
    "step_open_run",
)
