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
from typing import TYPE_CHECKING, Literal

from hydromodpy.core.exceptions import MeshError, SolverDivergedError, SolverInputError
from hydromodpy.core.state.run_state import RunState
from hydromodpy.solver.base.adapter_protocol import STOP_BEFORE_THE_SOLVE
from hydromodpy.solver.base.plan import (
    WATER_BUDGET_METRIC,
    WATER_BUDGET_WORST_METRIC,
    ProcessRun,
    RunContext,
    RunExecutionResult,
    SimulationPlan,
)
from hydromodpy.solver.modflow_common.options import (
    ModflowPreprocessOptions,
    ModflowRunOptions,
)

if TYPE_CHECKING:
    from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh

_PERCENT_DISCREPANCY_RE = re.compile(r"PERCENT\s+DISCREPANCY\s*=\s*([-+0-9.Ee]+)")


def percent_discrepancies(listing_dir: Path) -> list[float]:
    """Return every water-budget PERCENT DISCREPANCY a per-model listing prints.

    Best-effort and never raises: scans every ``*.lst`` except the simulation
    listing, and every ``*.list``, the extension FloPy gives the MODFLOW-NWT
    listing, in name order, and returns the values in the order they appear.

    A MODFLOW budget block prints two of them on one line, the cumulative
    volumes since the start of the simulation and the rates for the time step
    just solved. Both are kept: neither is more the budget than the other.
    """
    values: list[float] = []
    try:
        listings = sorted([*listing_dir.glob("*.lst"), *listing_dir.glob("*.list")])
    except OSError:
        return values
    for listing in listings:
        if listing.name == "mfsim.lst":
            continue
        try:
            text = listing.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in _PERCENT_DISCREPANCY_RE.finditer(text):
            try:
                values.append(float(match.group(1)))
            except ValueError:
                continue
    return values


_MODEL_BUDGET_HEADER_RE = re.compile(r"^\s*VOLUM\w*\s+BUDGET\s+FOR\s+ENTIRE\s+MODEL", re.IGNORECASE)
_ANY_BUDGET_HEADER_RE = re.compile(r"^\s*[\w ]*BUDGET\s+FOR\s+ENTIRE\s+MODEL", re.IGNORECASE)


def model_percent_discrepancies(listing_dir: Path) -> list[float]:
    """Return the PERCENT DISCREPANCY of the model volume budget only.

    A MODFLOW 6 listing prints one budget block per package family (SFR, LAK,
    water mover) before the ``VOLUME BUDGET FOR ENTIRE MODEL`` block. A package
    block divides by its own small flows, so a lake package at 2 per cent sat
    beside a model at 0.02 per cent. This keeps the model block alone. A listing
    with no recognisable block header falls back to every value, so a backend
    that prints a bare figure still reports it.
    """
    try:
        listings = sorted([*listing_dir.glob("*.lst"), *listing_dir.glob("*.list")])
    except OSError:
        return []
    values: list[float] = []
    for listing in listings:
        if listing.name == "mfsim.lst":
            continue
        try:
            text = listing.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        in_model_block = None  # None: no header seen yet
        for line in text.splitlines():
            if _MODEL_BUDGET_HEADER_RE.match(line):
                in_model_block = True
                continue
            if _ANY_BUDGET_HEADER_RE.match(line):
                in_model_block = False
                continue
            if in_model_block is False:
                continue
            for match in _PERCENT_DISCREPANCY_RE.finditer(line):
                try:
                    values.append(float(match.group(1)))
                except ValueError:
                    continue
    return values


def last_percent_discrepancy(listing_dir: Path) -> float | None:
    """Return the final water-budget PERCENT DISCREPANCY from a per-model listing.

    Best-effort and never raises: returns the last parsed value, or None when
    none is found.
    """
    values = percent_discrepancies(listing_dir)
    return values[-1] if values else None


def worst_percent_discrepancy(listing_dir: Path) -> float | None:
    """Return the signed PERCENT DISCREPANCY of largest magnitude, or None.

    The last block is not the worst one. A transient run that loses its budget
    in the middle and recovers by the final time step reports a clean final
    number, and :func:`last_percent_discrepancy` reads exactly that number. A
    deep-aquifer recession measured here closed the simulation at -190 % after
    touching -200 %, so even a run that never recovers understates itself.

    Recorded and not acted upon. A percent discrepancy divides by the mean of
    the inflow and the outflow, so the instant a transient model routes almost
    no water -- an intermittent reach going dry, a lake stage crossing its sill,
    the tail of any recession -- the quotient is large while the imbalance it
    describes is negligible. Rejecting on this number would refuse sound runs
    for arithmetic reasons. What a guard needs is the absolute imbalance against
    the scale of the run, which the listing also prints and nothing parses yet.

    Ties keep the first reading of that magnitude, so two opposite signs of
    equal size report the earlier one.
    """
    values = percent_discrepancies(listing_dir)
    if not values:
        return None
    return max(values, key=abs)


_SIMULATION_FAILURE_RE = re.compile(
    r"did not converge|convergence failure|premature termination", re.IGNORECASE
)


def simulation_listing_failure_lines(model_dir: Path, *, max_lines: int = 10) -> list[str]:
    """Return the lines of ``mfsim.lst`` that say why MODFLOW 6 stopped.

    Best-effort and never raises. Keeps the convergence-failure lines and the
    whole ``ERROR REPORT`` block MF6 prints at the end, without duplicates and
    with runs of spaces collapsed, and returns the last ``max_lines`` of them.
    A missing listing means mf6 never started or could not create it.
    """
    listing = model_dir / "mfsim.lst"
    try:
        text = listing.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ["mfsim.lst was not written: mf6 did not start or could not create it"]
    picked: list[str] = []
    in_report = False
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        if line.endswith("ERROR REPORT:"):
            in_report = True
        if (in_report or _SIMULATION_FAILURE_RE.search(line)) and line not in picked:
            picked.append(line)
    return picked[-max_lines:]


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


def build_preprocess_options(state: RunState) -> ModflowPreprocessOptions:
    """Build the flow pre-processing options from the runtime setup.

    Both supported flow backends consume the same preprocessing contract, so
    this helper keeps the mapping from launcher state to solver options in one
    place.  Every option not declared under ``[solver]`` keeps its
    ``ModflowPreprocessOptions`` default.
    """

    time_grid = getattr(state.setup, "time_grid", None)
    return ModflowPreprocessOptions(
        time_grid=time_grid,
        sink_fill=bool(state.cfg.solver.sink_fill),
        drain_band_depth_m=float(state.cfg.solver.drain_band_depth_m),
        drain_bed_thickness_m=float(state.cfg.solver.drain_bed_thickness_m),
        drain_conductance_floor_m2_s=float(state.cfg.solver.drain_conductance_floor_m2_s),
    )


def _requires_mt3dms_link(ctx: RunContext) -> bool:
    """Return whether one downstream MT3DMS run consumes this flow output."""
    return any(
        planned.process_type == "transport"
        and planned.solver == "mt3dms"
        and ctx.run.id in planned.depends_on
        for planned in ctx.plan.runs
    )


def resolve_modflow_runner(model_modflow: object) -> Literal["subprocess", "api"]:
    """Return the solve dispatch ('subprocess' or 'api') a flow model declares.

    The model answers for itself: what forces the in-process runner is a
    property of how MODFLOW 6 was built, and this helper is shared with a
    backend that has no such choice. A model that declares nothing is solved by
    subprocess, which is what NWT and every other backend do, byte for byte
    unchanged.

    Asking the built model is still the single source of truth for the
    dispatch: provenance reads it back so it records the engine that actually
    ran, not the one the configuration asked for.
    """
    declared = getattr(model_modflow, "required_runner", None)
    if declared is None:
        return "subprocess"
    return "api" if str(declared()) == "api" else "subprocess"


def require_cell_mesh(setup: object) -> PlanarCellMesh:
    """Return the planar cell mesh of the run, or say that no mesh step ran."""
    cell_mesh = getattr(setup, "cell_mesh", None)
    if cell_mesh is None:
        raise MeshError(
            "The solver needs the planar cell mesh of the run (setup.cell_mesh), and the "
            "mesh step has not built one."
        )
    return cell_mesh


def run_flow_model(
    ctx: RunContext,
    model_modflow,
    preprocess_options,
) -> RunExecutionResult:
    """Execute the shared lifecycle for one already-instantiated flow model.

    The solver-specific adapters only choose and configure the concrete flow
    backend. Once the model object exists, the execution steps are identical:

    1. run preprocessing against the shared ``flow`` and ``domain`` objects and
       the cell mesh of the run,
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
        flow_runtime_overrides=flow_runtime_overrides,
        cell_mesh=require_cell_mesh(state.setup),
    )
    if isinstance(flow_runtime_overrides, Mapping) and flow_runtime_overrides.get(
        STOP_BEFORE_THE_SOLVE
    ):
        return RunExecutionResult(primary_model=model_modflow)

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
            percent = last_percent_discrepancy(model_dir)
            if percent is not None:
                detail = f" Final water-budget PERCENT DISCREPANCY = {percent}."
            # The scratch holding mfsim.lst is often deleted with a test or CI
            # workspace, so the lines that say why the run stopped ride along.
            failure_lines = simulation_listing_failure_lines(model_dir)
            if failure_lines:
                detail += " mfsim.lst: " + " | ".join(failure_lines) + "."
            diagnostics_path = model_dir / "mfsim.lst"
            detail += xt3d_failure_hint(model_dir)
        raise SolverDivergedError(
            f"[HMPY.E401] Flow solver '{ctx.run.solver}' failed for run '{ctx.run.id}'."
            f"{detail} See {diagnostics_path} for diagnostics.",
            run_id=ctx.run.id,
        )
    metrics: dict[str, float] = {}
    flow_solve_time = getattr(model_modflow, "last_flow_solve_time_seconds", None)
    if flow_solve_time is not None:
        metrics["flow_solve_time_seconds"] = float(flow_solve_time)
    # Convergence and a closed budget are two questions. A run that converges and
    # writes heads with a large imbalance was otherwise indistinguishable from a
    # sound one, so the number rides with every run rather than only with a failure.
    discrepancies = model_percent_discrepancies(Path(model_modflow.full_path))
    if discrepancies:
        metrics[WATER_BUDGET_METRIC] = float(discrepancies[-1])
        metrics[WATER_BUDGET_WORST_METRIC] = float(max(discrepancies, key=abs))
    return RunExecutionResult(
        primary_model=model_modflow,
        solver_output_dir=Path(model_modflow.full_path),
        metrics=metrics,
    )


def xt3d_failure_hint(model_dir: Path) -> str:
    """Return a hint naming the XT3D switch when the written NPF uses XT3D.

    XT3D can keep the Newton outer loop cycling on some triangle meshes.
    The user needs the config key that turns it off.
    """
    for npf in sorted(Path(model_dir).glob("*.npf")):
        try:
            text = npf.read_text(errors="replace")
        except OSError:
            continue
        in_options = False
        for raw in text.splitlines():
            line = raw.strip().upper()
            if line.startswith("BEGIN OPTIONS"):
                in_options = True
            elif line.startswith("END OPTIONS"):
                break
            elif in_options and line.split()[:1] == ["XT3D"]:
                return (
                    " The NPF package uses XT3D. If the outer iterations cycle,"
                    " set mf6_enable_xt3d = false under [modflow6.runtime]"
                    " and run again."
                )
    return ""
