"""Shared helpers for MODFLOW-family flow adapters.

This module contains only MODFLOW-agnostic flow lifecycle logic:

- derive stable model names from the resolved simulation plan,
- build flow pre-processing options for solver backends,
- run the common pre/process sequence once a concrete flow model exists.

Post-processing (derived variables, result extraction) is handled by
the ``Catalog`` pipeline via ``post_run_results()``.

Keeping that code here avoids duplicating the same lifecycle in both
``modflow_nwt`` and ``modflow6`` adapters.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal

from hydromodpy.core.exceptions import SolverDivergedError, SolverInputError
from hydromodpy.simulation.planning.plan import (
    ProcessRun,
    RunContext,
    RunExecutionResult,
    SimulationPlan,
)
from hydromodpy.solver.modflow_common.options import (
    ModflowPreprocessOptions,
    ModflowRunOptions,
)

_PERCENT_DISCREPANCY_RE = re.compile(r"PERCENT\s+DISCREPANCY\s*=\s*([-+0-9.Ee]+)")


def _last_percent_discrepancy(listing_dir: Path) -> float | None:
    """Return the final water-budget PERCENT DISCREPANCY from a per-model listing.

    Best-effort and never raises: scans every ``*.lst`` except the simulation
    listing and returns the last parsed value, or None when none is found.
    """
    last: float | None = None
    try:
        listings = sorted(listing_dir.glob("*.lst"))
    except OSError:
        return None
    for listing in listings:
        if listing.name == "mfsim.lst":
            continue
        try:
            text = listing.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _PERCENT_DISCREPANCY_RE.finditer(text):
            try:
                last = float(match.group(1))
            except ValueError:
                continue
    return last


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

    raise SolverInputError(
        f"[HMPY.E405] Process run '{run.id}' is not present in the provided simulation plan."
    )


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
        override_name = str(flow_runtime_overrides.get("model_name_override", "") or "").strip()
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


def nwt_safe_name(name: str) -> str:
    """Collapse whitespace to underscores for a MODFLOW-NWT model name.

    MODFLOW-NWT (Fortran) truncates a NAME-file path at the first space, so a
    ``[simulation] name`` with spaces (e.g. ``"Example 12 launcher fast"``) must
    be sanitised before it reaches the solver files, or the run diverges on a
    truncated NAME file. Mirrors MF6's ``mf6_safe_name`` whitespace collapse;
    MODFLOW-NWT imposes no 16-char identifier limit, so no hashing is needed.
    """
    return re.sub(r"\s+", "_", str(name).strip())


def build_preprocess_options(state) -> ModflowPreprocessOptions:
    """Build the flow pre-processing options from the runtime setup.

    Both supported flow backends consume the same preprocessing contract, so
    this helper keeps the mapping from launcher state to solver options in one
    place.  Uses ``ModflowPreprocessOptions`` defaults directly.
    """

    time_grid = getattr(state.setup, "time_grid", None)
    return ModflowPreprocessOptions(time_grid=time_grid)


def _requires_mt3dms_link(ctx: RunContext) -> bool:
    """Return whether one downstream MT3DMS run consumes this flow output."""
    return any(
        planned.process_type == "transport"
        and planned.solver == "mt3dms"
        and ctx.run.id in planned.depends_on
        for planned in ctx.plan.runs
    )


def resolve_modflow_runner(model_modflow: object) -> Literal["subprocess", "api"]:
    """Return the solve dispatch ('subprocess' or 'api') for a flow model.

    Only the MODFLOW 6 backend exposes a ``mf6_runner`` runtime field. NWT and
    any other backend have no such field, so they default to 'subprocess' and
    stay byte-for-byte unchanged. A model that built exposed-band (marnage) runoff
    coupling specs forces the in-process 'api' runner, because that coupling sets
    the LAK RUNOFF per timestep through the BMI API.

    This is the single source of truth for the dispatch: provenance reads it
    back from the built model so it records the engine that actually ran, not
    the one the configuration asked for.
    """
    if getattr(model_modflow, "_exposed_band_runoff_specs", None):
        return "api"
    runtime = getattr(getattr(model_modflow, "modflow_config", None), "runtime", None)
    runner = getattr(runtime, "mf6_runner", "subprocess")
    return "api" if runner == "api" else "subprocess"


def run_flow_model(ctx: RunContext, model_modflow, preprocess_options) -> RunExecutionResult:
    """Execute the shared lifecycle for one already-instantiated flow model.

    The solver-specific adapters only choose and configure the concrete flow
    backend. Once the model object exists, the execution steps are identical:

    1. run preprocessing against the shared ``flow`` and ``domain`` objects,
    2. launch the numerical solve,
    3. return the result - post-processing is handled by ``post_run_results()``.
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

    # The numerical run is shared across flow backends: write files, execute
    # the solver, and link MT3DMS-compatible outputs only when a downstream
    # MT3DMS transport run depends on this flow run.
    success = model_modflow.processing(
        options=ModflowRunOptions(
            write_model=True,
            run_model=True,
            link_mt3dms=_requires_mt3dms_link(ctx),
            runner=resolve_modflow_runner(model_modflow),
        )
    )
    if not success:
        model_dir = Path(getattr(model_modflow, "full_path", "")).resolve()
        diagnostics_path = model_dir
        detail = ""
        if ctx.run.solver == "modflow6":
            percent = _last_percent_discrepancy(model_dir)
            if percent is not None:
                detail = f" Final water-budget PERCENT DISCREPANCY = {percent}."
            diagnostics_path = model_dir / "mfsim.lst"
        raise SolverDivergedError(
            f"[HMPY.E401] Flow solver '{ctx.run.solver}' failed for run '{ctx.run.id}'."
            f"{detail} See {diagnostics_path} for diagnostics.",
            run_id=ctx.run.id,
        )
    metrics: dict[str, float] = {}
    flow_solve_time = getattr(model_modflow, "last_flow_solve_time_seconds", None)
    if flow_solve_time is not None:
        metrics["flow_solve_time_seconds"] = float(flow_solve_time)
    return RunExecutionResult(
        primary_model=model_modflow,
        solver_output_dir=Path(model_modflow.full_path),
        metrics=metrics,
    )
