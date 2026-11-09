"""Shared helpers for MODFLOW-family flow adapters.

This module contains only MODFLOW-agnostic flow lifecycle logic:

- build flow pre-processing options for solver backends,
- ``build_flow_model`` and ``run_flow_model``, the two halves of the common
  lifecycle once a concrete solver object exists: the first builds the model
  in memory, the second writes the input files, solves and reads the listing,
- read back the folder, the solver object and the name of a solved run.

The name and the folder of a run come from the ``RunSlot`` the runner fills,
so nothing here derives a name. Result extraction and the derived variables
belong to the extract and derive steps of the workflow.

Keeping that code here avoids duplicating the same lifecycle in both
``modflow_nwt`` and ``modflow6`` adapters.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from hydromodpy.core.exceptions import (
    MeshError,
    ObservableNotAvailableError,
    SolverDivergedError,
)
from hydromodpy.solver.base.plan import (
    WATER_BUDGET_METRIC,
    WATER_BUDGET_WORST_METRIC,
    RunSlot,
    SolverRun,
)
from hydromodpy.solver.modflow_common.options import (
    ModflowPreprocessOptions,
    ModflowRunOptions,
)

if TYPE_CHECKING:
    from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
    from hydromodpy.model.model import Model

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


def nwt_safe_name(name: str) -> str:
    """Collapse whitespace to underscores for a MODFLOW-NWT model name.

    MODFLOW-NWT (Fortran) truncates a NAME-file path at the first space, so a
    ``[simulation] name`` with spaces (e.g. ``"Example 12 launcher fast"``) must
    be sanitised before it reaches the solver files, or the run diverges on a
    truncated NAME file. Mirrors MF6's ``mf6_safe_name`` whitespace collapse;
    MODFLOW-NWT imposes no 16-char identifier limit, so no hashing is needed.
    """
    return re.sub(r"\s+", "_", str(name).strip())


def build_preprocess_options(model: Model) -> ModflowPreprocessOptions:
    """Build the flow pre-processing options from the ``Model`` of the run.

    Both supported flow backends consume the same preprocessing contract, so
    this helper keeps the mapping from the model to solver options in one
    place. The time grid and the four ``[solver]`` settings are members of the
    model. Every option the model does not carry keeps its
    ``ModflowPreprocessOptions`` default.
    """

    return ModflowPreprocessOptions(
        time_grid=model.time.grid,
        sink_fill=model.options.sink_fill,
        drain_band_depth_m=model.options.drain_band_depth_m,
        drain_bed_thickness_m=model.options.drain_bed_thickness_m,
        drain_conductance_floor_m2_s=model.options.drain_conductance_floor_m2_s,
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


def require_cell_mesh(model: Model) -> PlanarCellMesh:
    """Return the planar cell mesh of the model, or say that no mesh step ran."""
    cell_mesh = model.geometry.cells
    if cell_mesh is None:
        raise MeshError(
            "The solver needs the planar cell mesh of the run (Model.geometry.cells), and the "
            "mesh step has not built one."
        )
    return cell_mesh


def build_flow_model(
    solver_model: Any,
    model: Model,
    options: BaseModel | None,
    slot: RunSlot,
    preprocess_options: ModflowPreprocessOptions,
) -> SolverRun:
    """Build one already-instantiated MODFLOW solver object in memory, writing nothing.

    The solver-specific adapter only chooses and configures the concrete
    backend, ``Modflow6`` or ``ModflowNwt``. Once the object exists the build is
    the same for both:

    1. check that the ``Model`` carries the planar cell mesh,
    2. pre-process: the grid, the packages and the disk inputs the backend
       needs, from the frozen ``Model``, which it never changes,
    3. return the built run, ``written`` and ``solved`` false, for
       ``run_flow_model`` to write and solve.

    Whether a downstream transport reads the flow output is a fact of the
    slot: the runner fills ``slot.hand_off`` with the ``reads`` of the runs
    that follow, and the NWT adapter turns ``face_flow`` into its LMT
    package on its ``build``. Nothing here reads a plan.
    """
    require_cell_mesh(model)
    solver_model.pre_processing(model, options=preprocess_options, slot=slot)
    return SolverRun(slot=slot, model=model, options=options, solver_model=solver_model)


def run_flow_model(solver_run: SolverRun, *, solver_name: str) -> SolverRun:
    """Write, solve and measure a built MODFLOW solver object, and return the solved run.

    The input files are written unless ``solver_run.written``. The solver
    object lists the files it wrote in ``input_files``, relative to its folder,
    and says in ``link_mt3dms`` whether to link MT3DMS-compatible outputs. The
    numerical run is the same for both MODFLOW backends:

    1. write the files, execute the solver and link the MT3DMS output,
    2. read the water budget the listing prints,
    3. return the run with its folder, its input files and its metrics.

    A solve that fails raises ``SolverDivergedError`` naming the run by
    ``solver_run.slot.name``. The runner puts the run id on it.
    """
    solver_model = solver_run.solver_model
    success = solver_model.processing(
        options=ModflowRunOptions(
            write_model=not solver_run.written,
            run_model=True,
            link_mt3dms=bool(getattr(solver_model, "link_mt3dms", False)),
            runner=resolve_modflow_runner(solver_model),
        )
    )
    if not success:
        model_dir = Path(getattr(solver_model, "full_path", "")).resolve()
        diagnostics_path = model_dir
        detail = ""
        if solver_name == "modflow6":
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
            f"[HMPY.E401] Flow solver '{solver_name}' failed for run "
            f"'{solver_run.slot.name}'.{detail} See {diagnostics_path} for diagnostics."
        )
    metrics: dict[str, float] = {}
    flow_solve_time = getattr(solver_model, "last_flow_solve_time_seconds", None)
    if flow_solve_time is not None:
        metrics["flow_solve_time_seconds"] = float(flow_solve_time)
    # Convergence and a closed budget are two questions. A run that converges and
    # writes heads with a large imbalance was otherwise indistinguishable from a
    # sound one, so the number rides with every run rather than only with a failure.
    discrepancies = model_percent_discrepancies(Path(solver_model.full_path))
    if discrepancies:
        metrics[WATER_BUDGET_METRIC] = float(discrepancies[-1])
        metrics[WATER_BUDGET_WORST_METRIC] = float(max(discrepancies, key=abs))
    return replace(
        solver_run,
        output_dir=Path(solver_model.full_path),
        input_files=tuple(getattr(solver_model, "input_files", ())),
        written=True,
        solved=True,
        metrics={**solver_run.metrics, **metrics},
    )


def resolve_solver_run_output(
    solver_run: SolverRun, *, name_attributes: Sequence[str]
) -> tuple[Path, Any, str]:
    """Return the output folder, the solver object and the model name of a solved run.

    A lightweight trial writes nothing to the store, so the only trace of the
    run is the folder its solver wrote in. ``name_attributes`` lists, in order,
    the attributes of the solver object that can hold the name of the model.
    The run is named by ``slot.name`` in the refusals.
    """
    output_dir = solver_run.output_dir
    solver_model = solver_run.solver_model
    if output_dir is None or solver_model is None:
        raise ObservableNotAvailableError(
            f"No solver output recorded for run {solver_run.slot.name!r}"
        )
    model_name = next(
        (
            value
            for value in (getattr(solver_model, attr, None) for attr in name_attributes)
            if value is not None
        ),
        None,
    )
    if model_name is None:
        raise ObservableNotAvailableError(f"Model name is missing for run {solver_run.slot.name!r}")
    return output_dir, solver_model, str(model_name)


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
                    " set mf6_enable_xt3d = false under [solver.modflow6.runtime]"
                    " and run again."
                )
    return ""
