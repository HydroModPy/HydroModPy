"""Shared helpers for MODFLOW-family flow adapters.

This module intentionally contains only solver-agnostic flow logic:

- derive stable model names from the resolved simulation plan,
- translate shared launcher settings into flow pre-processing options,
- persist the legacy pickle payload expected by older utilities,
- run the common pre/process/post sequence once a concrete flow model exists.

Keeping that code here avoids duplicating the same lifecycle in both
``modflownwt`` and ``modflow6`` adapters.
"""

from __future__ import annotations

import pickle
from pathlib import Path

from hydromodpy.simulation.plan import ProcessRun, SimulationPlan
from hydromodpy.simulation.runtime import RunContext, RunExecutionResult
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


def build_preprocess_options(state) -> ModflowPreprocessOptions:
    """Build the flow pre-processing options from the shared runtime settings.

    Both supported flow backends consume the same preprocessing contract, so
    this helper keeps the mapping from launcher state to solver options in one
    place.
    """

    settings = state.settings
    return ModflowPreprocessOptions(
        box=settings.box,
        sink_fill=settings.sink_fill,
        check_grid=settings.check_grid,
        plot_cross=settings.plot_cross,
        cross_ylim=tuple(settings.cross_ylim) if settings.cross_ylim else None,
    )


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
        flow=state.flow,
        domain=state.domain,
        options=preprocess_options,
    )

    # Keep emitting the legacy payload immediately after preparation so older
    # post-processing utilities can reopen the prepared model using the
    # historical file convention.
    _persist_pre_run_payload(state.workspace, model_modflow.model_name, model_modflow)

    # The numerical run is shared across flow backends: write files, execute
    # the solver, and link MT3DMS-compatible outputs when available.
    success = model_modflow.processing(
        options=ModflowRunOptions(write_model=True, run_model=True, link_mt3dms=True)
    )
    if success:
        # Post-processing reads solver outputs from disk, so it only makes
        # sense after a successful solve.
        model_modflow.post_processing(
            options=ModflowPostprocessOptions(
                watertable_elevation=True,
                watertable_depth=True,
                seepage_areas=True,
                outflow_drain=True,
                accumulation_flux=True,
                intermittency_monthly=True,
            )
        )

    return RunExecutionResult(primary_model=model_modflow)
