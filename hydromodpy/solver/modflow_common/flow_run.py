"""The flow lifecycle shared by the MODFLOW solvers: options, build, run, read back, final state."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import pandas as pd
from pydantic import BaseModel

from hydromodpy.core.exceptions import (
    MeshError,
    ObservableNotAvailableError,
    SolverDivergedError,
)
from hydromodpy.core.fields.nodata import SENTINEL_ABS_THRESHOLD
from hydromodpy.solver.base.plan import (
    WATER_BUDGET_METRIC,
    WATER_BUDGET_WORST_METRIC,
    RunSlot,
    SolverRun,
)
from hydromodpy.solver.modflow_common.listing import (
    last_percent_discrepancy,
    model_percent_discrepancies,
    simulation_listing_failure_lines,
    xt3d_failure_hint,
)
from hydromodpy.solver.modflow_common.options import (
    ModflowPreprocessOptions,
    ModflowRunOptions,
)

if TYPE_CHECKING:
    from hydromodpy.mesh.planar.planar_cell_mesh import PlanarCellMesh
    from hydromodpy.model.model import Model


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
    3. return the run with its folder, its input files, its metrics and the
       wall time of the solve, ``solve_s``, which the solver object measured in
       ``last_flow_solve_time_seconds``.

    The time of the solve is no metric: it stays out of the tables of the run,
    and the ``run_solver`` step writes it to ``profile.json``.

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
        solve_s=getattr(solver_model, "last_flow_solve_time_seconds", None),
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


def final_state_head(
    raw: Any, *, nlay: int, n_cells: int, sentinels: Sequence[float] = ()
) -> np.ndarray:
    """Return a head record as the ``(nlay, n_cells)`` float64 head of ``final_state/``.

    ``raw`` is the last record of a head file, read in double. A cell that
    holds a MODFLOW sentinel, ``HDRY`` or ``HNOFLO`` of about 1e30 in absolute
    value, becomes NaN. ``sentinels`` lists more values the solver was
    configured with (the ``hdry`` and ``hnoflo`` of MODFLOW-NWT, which are no
    1e30), and a cell within 1 m of one of them becomes NaN too, as the
    head stack of the store does.
    """
    head = np.array(raw, dtype=np.float64, copy=True).reshape(int(nlay), int(n_cells))
    masked = np.abs(head) > SENTINEL_ABS_THRESHOLD
    for sentinel in sentinels:
        masked |= np.isclose(head, float(sentinel), atol=1.0)
    head[masked] = np.nan
    return head


def end_of_last_period(start: object | None, seconds: float) -> pd.Timestamp | None:
    """Return the instant ``seconds`` after ``start``, the end of the last period, or ``None``.

    ``start`` is the calendar start of the run. A run without one has no
    calendar, and its ``final_state/`` carries no ``at``.
    """
    if start is None:
        return None
    return pd.Timestamp(start) + pd.to_timedelta(float(seconds), unit="s")
