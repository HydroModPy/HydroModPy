"""Shared helpers for MODFLOW-family flow adapters.

This module intentionally contains only solver-agnostic flow logic:

- derive stable model names from the resolved simulation plan,
- build flow pre-processing options for solver backends,
- optionally emit one explicit legacy compatibility artifact,
- run the common pre/process/post sequence once a concrete flow model exists.

Keeping that code here avoids duplicating the same lifecycle in both
``modflownwt`` and ``modflow6`` adapters.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from hydromodpy.simulation.adapters.flow import legacy_compat
from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.modflow_common.options import (
    ModflowPostprocessOptions,
    ModflowPreprocessOptions,
    ModflowRunOptions,
)


def _has_single_process_run(plan: SimulationPlan, process_type: str) -> bool:
    """Return ``True`` when *plan* contains exactly one run of *process_type*.

    The flow adapters use this to decide whether they can keep the base model
    name unchanged or must append a deterministic suffix to avoid collisions.
    """

    return sum(1 for run in plan.runs if run.process_type == process_type) == 1


def _run_label(plan: SimulationPlan, run: ProcessRun) -> str:
    """Return a short stable label for *run* inside its process family.

    Labels are positional within the family, not global to the plan. That
    keeps generated names compact and predictable across repeated runs.
    """

    same_type_runs = [planned for planned in plan.runs if planned.process_type == run.process_type]
    for index, planned in enumerate(same_type_runs, start=1):
        if planned.id == run.id:
            prefix = {
                "flow": "f",
                "transport": "t",
            }.get(run.process_type, "r")
            return f"{prefix}{index}"

    raise ValueError(f"Process run '{run.id}' is not present in the provided simulation plan.")


def flow_model_name(plan: SimulationPlan, base_name: str, run: ProcessRun) -> str:
    """Return the stable model name used for one flow run.

    When the plan contains a single flow run, the launcher base model name is
    reused unchanged. When several flow runs exist, a short suffix such as
    ``_f1`` or ``_f2`` is appended so each solver writes into its own folder.
    """

    if _has_single_process_run(plan, "flow"):
        return base_name
    return f"{base_name}_{_run_label(plan, run)}"


def resolve_run_model_name(ctx) -> str:
    """Resolve the model name from the run context.

    Canonical source is ``ctx.state.setup.run_id``.
    When the plan has multiple flow runs, a positional suffix is appended.
    """
    flow_runtime_overrides = getattr(ctx.state.setup, "flow_runtime_overrides", None)
    if isinstance(flow_runtime_overrides, Mapping):
        override_name = str(
            flow_runtime_overrides.get("model_name_override", "") or ""
        ).strip()
        if override_name:
            return flow_model_name(ctx.plan, override_name, ctx.run)
    return flow_model_name(ctx.plan, resolve_base_model_name(ctx.state.setup), ctx.run)


def resolve_base_model_name(setup) -> str:
    """Resolve the launcher base model name from runtime setup state.

    Canonical source is ``setup.run_id`` in the modern simulation runtime.
    When missing or blank, ``"default"`` is returned.
    """
    run_id = str(getattr(setup, "run_id", "") or "").strip()
    if run_id:
        return run_id
    return "default"


def build_preprocess_options(state) -> ModflowPreprocessOptions:
    """Build the flow pre-processing options from the runtime setup.

    Both supported flow backends consume the same preprocessing contract, so
    this helper keeps the mapping from launcher state to solver options in one
    place.  Uses ``ModflowPreprocessOptions`` defaults directly.
    """

    time_grid = getattr(state.setup, "time_grid", None)
    return ModflowPreprocessOptions(time_grid=time_grid)


def run_flow_model(ctx: RunContext, model_modflow, preprocess_options) -> RunExecutionResult:
    """Execute the shared lifecycle for one already-instantiated flow model.

    The solver-specific adapters only choose and configure the concrete flow
    backend. Once the model object exists, the execution steps are identical:

    1. run preprocessing against the shared ``flow`` and ``domain`` objects,
    2. optionally persist one legacy compatibility pickle when explicitly requested,
    3. launch the numerical solve,
    4. run standard post-processing only if the solve succeeds.
    """

    state = ctx.state
    flow_runtime_overrides = getattr(state.setup, "flow_runtime_overrides", None)
    # Pre-processing materializes the grid, packages, and disk inputs for the
    # chosen flow backend using the already-prepared shared domain objects.
    model_modflow.pre_processing(
        flow=state.setup.flow,
        domain=state.setup.domain,
        options=preprocess_options,
        mesh_planar=getattr(state.setup, "mesh_planar", None),
        mesh_support=getattr(state.setup, "mesh_support", None),
        flow_runtime_overrides=flow_runtime_overrides,
    )

    # The canonical runtime contract stores concrete solver instances in
    # ``state.execution.models_by_run_id``. The historical pickle artifact is
    # therefore opt-in compatibility output only.
    if legacy_compat.should_write_legacy_pre_run_pickle(flow_runtime_overrides):
        legacy_compat.write_legacy_pre_run_pickle(
            state.setup.workspace,
            model_modflow.model_name,
            model_modflow,
        )

    # The numerical run is shared across flow backends: write files, execute
    # the solver, and link MT3DMS-compatible outputs when available.
    success = model_modflow.processing(
        options=ModflowRunOptions(write_model=True, run_model=True, link_mt3dms=True)
    )
    if not success:
        diagnostics_path = Path(getattr(model_modflow, "full_path", "")).resolve()
        if ctx.run.solver == "modflow6":
            diagnostics_path = diagnostics_path / "mfsim.lst"
        raise RuntimeError(
            f"Flow solver '{ctx.run.solver}' failed for run '{ctx.run.id}'. "
            f"See {diagnostics_path} for diagnostics."
        )
    skip_solver_postprocess = bool(
        isinstance(flow_runtime_overrides, Mapping)
        and flow_runtime_overrides.get("skip_solver_postprocess", False)
    )
    if success and not skip_solver_postprocess:
        active_bc = {
            str(name).strip().lower()
            for name in getattr(state.setup.flow, "active_bc", [])
            if str(name).strip()
        }
        has_drainage = "drainage" in active_bc
        has_east_side_dirichlet = "east_side" in active_bc
        postprocess_cfg = getattr(getattr(ctx.state.cfg, "postprocess", None), "flow", None)
        intermittency_cfg = getattr(postprocess_cfg, "intermittency", None)

        # Post-processing reads solver outputs from disk, so it only makes
        # sense after a successful solve.
        model_modflow.post_processing(
            options=ModflowPostprocessOptions(
                watertable_elevation=True,
                watertable_depth=True,
                seepage_areas=True,
                outflow_drain=has_drainage,
                outlet_discharge_east_side_m3_s=has_east_side_dirichlet,
                accumulation_flux=has_drainage,
                intermittency_yearly=bool(
                    getattr(intermittency_cfg, "yearly", False)
                ),
                intermittency_monthly=bool(
                    getattr(intermittency_cfg, "monthly", False)
                ),
                intermittency_weekly=bool(
                    getattr(intermittency_cfg, "weekly", False)
                ),
                intermittency_daily=bool(
                    getattr(intermittency_cfg, "daily", False)
                ),
                native_mesh_npz=bool(
                    getattr(postprocess_cfg, "native_mesh_npz", False)
                ),
                native_mesh_csv=bool(
                    getattr(postprocess_cfg, "native_mesh_csv", False)
                ),
                native_mesh_vtu=bool(
                    getattr(postprocess_cfg, "native_mesh_vtu", False)
                ),
                native_mesh_png=bool(
                    getattr(postprocess_cfg, "native_mesh_png", False)
                ),
            )
        )

    return RunExecutionResult(primary_model=model_modflow)
