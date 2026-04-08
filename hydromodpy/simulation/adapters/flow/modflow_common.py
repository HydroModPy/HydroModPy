"""Shared helpers for MODFLOW-family flow adapters.

This module intentionally contains only solver-agnostic flow logic:

- derive stable model names from the resolved simulation plan,
- build flow pre-processing options for solver backends,
- persist the legacy pickle payload expected by older utilities,
- run the common pre/process/post sequence once a concrete flow model exists.

Keeping that code here avoids duplicating the same lifecycle in both
``modflownwt`` and ``modflow6`` adapters.
"""

from __future__ import annotations

import pickle
from pathlib import Path

from hydromodpy.simulation.planning.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.planning.plan import RunContext, RunExecutionResult
from hydromodpy.solver.modflow_nwt import (
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
    run_id = str(getattr(ctx.state.setup, "run_id", "") or "").strip()
    if not run_id:
        run_id = "default"
    return flow_model_name(ctx.plan, run_id, ctx.run)


def resolve_base_model_name(setup) -> str:
    """Resolve the launcher base model name from runtime setup state.

    Canonical source is ``setup.run_id`` in the modern simulation runtime.
    Falls back to ``setup.model_name`` for compatibility.
    When missing or blank, ``"default"`` is returned.
    """
    run_id = str(getattr(setup, "run_id", "") or "").strip()
    if run_id:
        return run_id
    setup_name = str(getattr(setup, "model_name", "") or "").strip()
    if setup_name:
        return setup_name
    return "default"


def build_preprocess_options(state) -> ModflowPreprocessOptions:
    """Build the flow pre-processing options from the runtime setup.

    Both supported flow backends consume the same preprocessing contract, so
    this helper keeps the mapping from launcher state to solver options in one
    place.  Uses ``ModflowPreprocessOptions`` defaults directly.
    """

    time_grid = getattr(state.setup, "time_grid", None)
    return ModflowPreprocessOptions(time_grid=time_grid)


def _persist_pre_run_payload(workspace, model_name: str, model_modflow) -> None:
    """Write the legacy pre-run pickle expected by downstream utilities.

    Several existing post-processing paths still reopen this file using the
    historical ``results_<model>.pkl`` convention. The adapter therefore keeps
    emitting the same shape even though execution is now orchestrated through
    ``SimulationRunner``.
    """

    pickle_path = Path(workspace.simulations_folder) / model_name / f"results_{model_name}.pkl"
    pickle_path.parent.mkdir(parents=True, exist_ok=True)
    with pickle_path.open("wb") as fh:
        pickle.dump(
            {
                "list_model_name": [model_name],
                "list_model_modflow": [model_modflow],
            },
            fh,
        )


def run_flow_model(ctx: RunContext, model_modflow, preprocess_options) -> RunExecutionResult:
    """Execute the shared lifecycle for one already-instantiated flow model.

    The solver-specific adapters only choose and configure the concrete flow
    backend. Once the model object exists, the execution steps are identical:

    1. run preprocessing against the shared ``flow`` and ``domain`` objects,
    2. persist the compatibility pickle for downstream readers,
    3. launch the numerical solve,
    4. run standard post-processing only if the solve succeeds.
    """

    state = ctx.state
    # Pre-processing materializes the grid, packages, and disk inputs for the
    # chosen flow backend using the already-prepared shared domain objects.
    model_modflow.pre_processing(
        flow=state.setup.flow,
        domain=state.setup.domain,
        options=preprocess_options,
    )

    # Keep emitting the legacy payload immediately after preparation so older
    # post-processing utilities can reopen the prepared model using the
    # historical file convention.
    _persist_pre_run_payload(state.setup.workspace, model_modflow.model_name, model_modflow)

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
    if success:
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
            )
        )

    return RunExecutionResult(
        primary_model=model_modflow,
        solver_output_dir=Path(model_modflow.full_path),
    )
