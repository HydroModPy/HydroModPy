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
from hydromodpy.core.state.result_dirs import run_dir_rel
from hydromodpy.results.catalog.registration import portable_config_source, split_stem_version
from hydromodpy.results.lineage import Lineage
from hydromodpy.results.outcome import read_outcome
from hydromodpy.results.storage.attempt import claim_reserved_directory, claim_run_directory
from hydromodpy.results.storage.run_facts import RunFacts, read_facts
from hydromodpy.solver.base.registry import solvers
from hydromodpy.workflow.steps.prepare_solver.facts import (
    collect_run_facts,
    primary_run_for_simulation,
)
from hydromodpy.workflow.steps.prepare_solver.freeze import freeze_run_config
from hydromodpy.workflow.steps.prepare_solver.prepare import (
    step_persist_geographic,
    step_persist_mesh,
)
from hydromodpy.workflow.steps.prepare_solver.restart import (
    WindowSource,
    resolve_restart_source,
    window_input_entry,
)

if TYPE_CHECKING:
    from hydromodpy.core.state.run_state import WorkflowContext
    from hydromodpy.results.storage.run_store import RunStore
    from hydromodpy.solver.modflow_common.binaries import SolverEngine

logger = get_logger(__name__)


def _execution_mode(ctx: WorkflowContext, solver_name: str | None) -> str:
    """Return the solve dispatch this run uses: 'subprocess' or 'api'.

    The built flow model, once it exists, states the dispatch that really
    ran: a coupling of the build can force the in-process runner. Before the
    build, the backend's own options decide: a backend that declares a
    ``runner`` reads it, and every other backend runs its executable.

    The declared ``runner`` is the fallback, not the answer, so no layer
    outside the backend names the one that has the choice.
    """
    executed = _built_model_runner(ctx, solver_name)
    if executed is not None:
        return executed
    if not solver_name:
        return "subprocess"
    try:
        options = ctx.cfg.solver.options_of(solver_name)
    except ValueError:
        # An unregistered solver is refused later, by the plan itself.
        return "subprocess"
    runner = getattr(options, "runner", None)
    return "subprocess" if runner is None else str(runner)


def _built_model_runner(ctx: WorkflowContext, solver_name: str) -> str | None:
    """Return the dispatch of the built flow model, or None before it exists."""
    from hydromodpy.solver.modflow_common.flow_adapter_helpers import resolve_modflow_runner

    execution = getattr(ctx, "execution", None)
    plan = getattr(execution, "simulation_plan", None)
    solver_runs = getattr(execution, "solver_runs", None) or {}
    if plan is None or not solver_runs:
        return None
    for run in getattr(plan, "runs", ()) or ():
        is_primary_flow = (
            getattr(run, "process_type", None) == "flow"
            and getattr(run, "solver", None) == solver_name
        )
        if not is_primary_flow:
            continue
        solver_run = solver_runs.get(getattr(run, "id", None))
        if solver_run is not None and solver_run.solver_model is not None:
            return resolve_modflow_runner(solver_run.solver_model)
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
    solver_runs = ctx.execution.solver_runs
    for run in getattr(plan, "runs", ()) or ():
        if run.process_type == "flow" and run.solver == solver_name and run.id in solver_runs:
            read_back = getattr(solver_runs[run.id].solver_model, "resolved_solver_options", None)
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
        _, primary_solver = primary_run_for_simulation(plan)
        _write_run_environment(ctx, str(sim_id), primary_solver, store=store)
    except Exception:
        # The run is solved: a missing provenance note must not fail it.
        logger.exception("Failed to refresh the run environment for sim %s", str(sim_id)[:8])


def _crs_grid_mapping_attrs(crs: object) -> dict[str, object]:
    """Return CF grid-mapping attrs for a CRS value."""
    from pyproj import CRS
    from pyproj.exceptions import CRSError

    try:
        parsed = CRS.from_user_input(crs)
        attrs = dict(parsed.to_cf())
        if "crs_wkt" not in attrs:
            attrs["crs_wkt"] = parsed.to_wkt()
        epsg = parsed.to_epsg()
        if epsg is not None:
            attrs["epsg_code"] = int(epsg)
        return attrs
    except CRSError:
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
    source. The request id of the run took the digest of the state it reads from
    that source before this call, so its name and its ``sim_id`` count for nothing.
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


def _register_tracked_input_files(ctx: WorkflowContext, *, store: RunStore) -> None:
    """Walk the config tree and record every InputFile-marked path."""
    from hydromodpy.core.tracking import collect_input_files

    # Anchor relative paths on the project, not on the shell's working
    # directory: a bare filename is resolved under <workspace>/data/<family>/
    # everywhere else, and tracking it from the cwd silently dropped it.
    project_root = getattr(getattr(ctx.setup, "workspace", None), "project_root", None)
    try:
        entries = collect_input_files(ctx.cfg, base=project_root)
    except Exception as exc:
        # Tracking is provenance: a configuration the walker cannot read must not stop the run.
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


def solver_binaries(
    cfg: Any, *, bin_path: str | Path | None = None, fetch: bool = True
) -> dict[str, Path | None]:
    """Return the binary each solver of the simulation of *cfg* calls, by solver name.

    A solver that has no binary maps to ``None``. The path is the one the run
    would execute: the shared library for a MODFLOW 6 run driven through its API,
    the executable otherwise. This asks for no version and runs nothing. A binary
    that is absent is looked for the way the run looks for it, and maps to
    ``None`` when it cannot be found. *bin_path* is the folder of the binaries, the
    one a workspace resolves when not given. A run asks to *fetch* a managed binary
    that is absent, as its solve would; a plan or a dry run only looks.
    """
    from hydromodpy.core.workspace.workspace import resolve_bin_path
    from hydromodpy.solver.base.planner import SimulationPlanner

    simulation = getattr(cfg, "simulation", None)
    if simulation is None:
        return {}
    if bin_path is None:
        bin_path = resolve_bin_path()
    plan = SimulationPlanner().build(simulation)
    found: dict[str, Path | None] = {}
    for run in plan.runs:
        if run.process_type == "mesh" or run.solver in found:
            continue
        try:
            options = cfg.solver.options_of(run.solver)
        except ValueError:
            options = None
        runner = getattr(options, "runner", None)
        mode = "subprocess" if runner is None else str(runner)
        found[run.solver] = _solver_path(run.solver, mode, bin_path, fetch=fetch)
    return found


def _solver_path(
    solver: str, mode: str, bin_path: str | Path | None, *, fetch: bool
) -> Path | None:
    """Return the file *solver* executes in *mode*, or None when it has none or none is found."""
    from hydromodpy.solver.modflow_common.binaries import (
        SOLVER_EXECUTABLES,
        SOLVER_LIBRARIES,
        ensure_solver_binary,
        ensure_solver_library,
        locate_solver_binary,
    )

    library = mode == "api" and solver in SOLVER_LIBRARIES
    name = SOLVER_LIBRARIES[solver] if library else SOLVER_EXECUTABLES.get(solver)
    if name is None:
        return None
    try:
        if not fetch:
            return locate_solver_binary(bin_path, name) if bin_path else None
        if library:
            return Path(ensure_solver_library(name, bin_path))
        return Path(ensure_solver_binary(name, bin_path))
    except Exception:  # noqa: BLE001 - a binary that cannot be found only leaves the key without it
        logger.debug("No binary found for solver %s", solver, exc_info=True)
        return None


def _solver_category(process_type: str, solver: str) -> str | None:
    """Return the category the backend of the primary run declares, or None for a mesh-only plan."""
    if process_type == "mesh":
        return None
    return solvers.get(process_type, solver).category


def initial_facts(ctx: WorkflowContext, *, solution_key: str | None = None) -> RunFacts:
    """Return the facts of the attempt as the context knows them at opening.

    *solution_key* is what the runner computed once the inputs were resolved
    (:func:`~hydromodpy.results.request_identity.solution_key`). It is sealed as
    ``identity.config_hash``. A run opened by other means than the runner, a kept
    trial, has none, and no later run is told identical to it.
    """
    workspace = ctx.setup.workspace
    assert workspace is not None and ctx.run_dir is not None and ctx.sim_id is not None
    project_root = Path(workspace.project_root)
    outcome = read_outcome(ctx.run_dir)
    assert outcome is not None
    stored = read_facts(ctx.run_dir)
    plan = ctx.execution.simulation_plan
    process_type, primary_solver = primary_run_for_simulation(plan)
    facts = collect_run_facts(ctx)
    facts["config_hash"] = solution_key
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
        solver_category=_solver_category(process_type, primary_solver),
        lineage=ctx.lineage if ctx.lineage is not None else Lineage(),
        calibrated_by=ctx.calibrated_by,
        **facts,
    )


def bind_window_source(
    ctx: WorkflowContext, *, store: RunStore, window_source: WindowSource
) -> None:
    """Record the window a window of a chain starts from as an input and as its parent.

    The input is the row ``initial_state`` of ``inputs.json``: the ``final_state/`` of
    the source relative to the project, with the digest of its state, which is also
    the ``window_state`` of the request id. The lineage names the source run.
    """
    project_root = Path(store.workspace_path or store.run_dir.parent.parent)
    store.facts.put_input(window_input_entry(project_root, window_source))
    lineage = store.facts.lineage
    if window_source.sim_id is not None and lineage.parent_sim_id is None:
        store.facts.lineage = lineage.model_copy(
            update={
                "parent_sim_id": window_source.sim_id,
                "parent_hint": run_dir_rel(Path(window_source.run_dir).name),
            }
        )
        ctx.lineage = store.facts.lineage


def step_open_run(ctx: WorkflowContext, *, store: RunStore) -> None:
    """Record what the run was built from in its store.

    The store is the one of ``ctx.run_dir``, opened by the caller on the
    facts :func:`initial_facts` built.
    """
    assert ctx.sim_id is not None
    plan = ctx.execution.simulation_plan
    _, primary_solver = primary_run_for_simulation(plan)
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
        # Same as above: the environment note is provenance, the run goes on without it.
        logger.exception("Failed to capture run environment for sim %s", ctx.sim_id[:8])

    _register_tracked_input_files(ctx, store=store)

    step_persist_mesh(ctx, ctx.sim_id, store=store)
    step_persist_geographic(ctx, ctx.sim_id, store=store)


__all__ = (
    "bind_run_directory",
    "bind_window_source",
    "initial_facts",
    "planned_recipe",
    "refresh_run_environment",
    "solver_binaries",
    "step_open_run",
)
