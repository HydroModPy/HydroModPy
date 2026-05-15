"""Strict experimental Picard/L-scheme initializer for steady Boussinesq.

This module is intentionally isolated from the default runtime selection path.
It is an investigation helper for difficult steady obstacle cases.  The method
keeps the original head-only problem definition: no artificial minimum
saturated thickness is introduced and no drainage/surface conductance is added.

The Picard iterate solves a lagged linear transmissivity problem, adds a purely
algorithmic L-scheme diagonal damping term, relaxes the update, projects the
head into the physical bounds, and evaluates the strict bounded residual.
"""

from __future__ import annotations

import csv
import json
import math
import time
import warnings
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

import numpy as np

from hydromodpy.solver.boussinesq.assembly.fluxes import (
    accumulate_internal_flux_residual,
    harmonic_conductivity,
    internal_edge_flux_from_head,
    saturated_thickness_from_head,
)
from hydromodpy.solver.boussinesq.assembly.inputs import (
    as_cell_vector,
    as_prescribed_head_cell_vector,
    finalize_boundary_constrained_residual,
)
from hydromodpy.solver.boussinesq.assembly.types import BoussinesqAssembly
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
)
from hydromodpy.solver.boussinesq.runtimes import petsc_vi_obstacle
from hydromodpy.solver.boussinesq.runtimes.execution_common import (
    apply_residual_tolerance,
    build_runtime_result,
    residual_norm_inf,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_common import (
    _coo_to_csr,
    _require_petsc,
    _snes_reason_label,
)

PICARD_LSCHEME_SUMMARY_JSON = "picard_lscheme_summary.json"
PICARD_LSCHEME_ITERATIONS_CSV = "picard_lscheme_iterations.csv"
PICARD_LSCHEME_FINAL_CELLS_CSV = "picard_lscheme_final_cells.csv"
PICARD_VI_CYCLE_SUMMARY_JSON = "picard_vi_cycle_summary.json"
PICARD_VI_CYCLES_CSV = "picard_vi_cycles.csv"

_MIN_DISTANCE_M = 1.0e-12
_DRY_THICKNESS_TOL_M = 1.0e-12


@dataclass(frozen=True, kw_only=True)
class PicardLschemeOptions:
    """Options for the experimental strict bounded Picard/L-scheme solve."""

    picard_max_iterations: int = 500
    picard_tolerance_residual_inf: float = 1.0e-6
    picard_tolerance_update_inf: float = 1.0e-6
    picard_relaxation_omega: float = 0.5
    picard_omega_min: float = 0.05
    picard_lscheme_L: float | Literal["auto"] = "auto"
    picard_project_bounds: bool = True
    picard_final_vi_check: bool = False
    picard_fail_if_final_vi_fails: bool = False
    picard_output_diagnostics: bool = True
    picard_residual_growth_factor: float = 1.25
    picard_usable_residual_inf: float = 1.0e-3
    picard_top_n_cells: int = 500


@dataclass(frozen=True)
class PicardIterationRecord:
    """One persisted Picard iteration diagnostic row."""

    iteration: int
    omega: float
    Lstab: float
    residual_inf: float
    projected_residual_inf: float
    update_inf: float
    active_top_count: int
    active_bottom_count: int
    free_count: int
    physically_dry_count: int
    max_lower_violation: float
    max_upper_violation: float
    linear_solve_status: str
    note: str = ""


@dataclass(frozen=True, kw_only=True)
class PicardViCycleOptions:
    """Options for strict Picard/VI cycling."""

    cycle_max: int = 10
    picard_steps_per_cycle: int = 200
    vi_max_iterations_per_cycle: int = 20
    accept_failed_vi_residual_factor: float = 0.5
    accept_failed_vi_if_bounds_ok: bool = True
    final_vi_required: bool = True
    output_diagnostics: bool = True
    picard_options: PicardLschemeOptions = field(
        default_factory=lambda: PicardLschemeOptions(
            picard_max_iterations=200,
            picard_relaxation_omega=1.0,
            picard_final_vi_check=False,
            picard_fail_if_final_vi_fails=False,
            picard_output_diagnostics=False,
        )
    )


@dataclass(frozen=True)
class PicardViCycleRecord:
    """One persisted Picard/VI cycle diagnostic row."""

    cycle: int
    start_residual_inf: float
    picard_iterations: int
    picard_residual_inf: float
    picard_stop_reason: str
    vi_attempted: bool
    vi_converged: bool
    vi_iterations: int
    vi_residual_inf: float
    vi_termination_reason: str
    vi_error: str
    accepted_source: str
    accepted_residual_inf: float
    active_top_count: int
    active_bottom_count: int
    free_count: int
    physically_dry_count: int
    note: str = ""


def bounded_picard_lscheme(
    inputs: SteadySolveInputs,
    *,
    picard_options: PicardLschemeOptions | None = None,
    diagnostics_dir: str | Path | None = None,
    case_id: str = "",
) -> RuntimeSolveResult:
    """Run the experimental strict bounded Picard/L-scheme initializer."""
    options = picard_options or PicardLschemeOptions()
    start = time.perf_counter()
    mesh = inputs.mesh
    prescribed = _prescribed_head_cells(inputs.prescribed_head_m_by_cell, n_cells=mesh.n_cells)
    lower, upper, prescribed_mask = _physical_bounds(mesh, prescribed)
    head = _clip_head(
        np.asarray(inputs.head_initial_guess_m, dtype=float).reshape(-1),
        lower=lower,
        upper=upper,
        project_bounds=bool(options.picard_project_bounds),
    )

    raw_assembly = _assemble_strict_steady_residual(
        mesh,
        head,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
    )
    result = _runtime_result_from_raw_assembly(
        mesh=mesh,
        raw_assembly=raw_assembly,
        head=head,
        lower=lower,
        upper=upper,
        prescribed_mask=prescribed_mask,
        inputs=inputs,
        backend_name="bounded_picard_lscheme",
        iterations=0,
        termination_reason="Picard initial residual",
        extra_diagnostics={
            "method": "bounded_picard_lscheme",
            "picard_stop_reason": "initial",
            "strict_problem_definition": True,
        },
    )
    initial_residual = float(result.residual_norm_inf)
    records: list[PicardIterationRecord] = []
    stop_reason = "max_iterations"
    linear_solve_status = "not_started"
    final_vi_result: RuntimeSolveResult | None = None
    final_vi_error: str | None = None
    omega_final = float(options.picard_relaxation_omega)
    Lstab_final = 0.0

    if initial_residual <= float(options.picard_tolerance_residual_inf):
        stop_reason = "converged_target_residual"
    else:
        for iteration in range(1, int(options.picard_max_iterations) + 1):
            iter_start_residual = float(result.residual_norm_inf)
            try:
                matrix, rhs, Lstab = _picard_linear_system(
                    mesh,
                    head_old=head,
                    recharge_rate_m_s=inputs.recharge_rate_m_s,
                    well_flux_m3_s=inputs.well_flux_m3_s,
                    prescribed_head_m_by_cell=prescribed,
                    prescribed_mask=prescribed_mask,
                    drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
                    lscheme_L=options.picard_lscheme_L,
                )
                Lstab_final = float(Lstab)
                trial = _solve_sparse_system(matrix, rhs)
                linear_solve_status = "ok"
            except Exception as exc:  # noqa: BLE001 - diagnostic path
                stop_reason = "linear_solve_failed"
                linear_solve_status = f"{type(exc).__name__}: {exc}"
                break

            if not np.all(np.isfinite(trial)):
                stop_reason = "linear_solve_failed"
                linear_solve_status = "nonfinite_solution"
                break

            accepted, omega_used, note = _accept_relaxed_candidate(
                mesh=mesh,
                head_old=head,
                trial=trial,
                lower=lower,
                upper=upper,
                prescribed_mask=prescribed_mask,
                inputs=inputs,
                prescribed_head_m_by_cell=prescribed,
                options=options,
                previous_projected_residual_inf=iter_start_residual,
            )
            head_next, next_result = accepted
            update_inf = float(np.max(np.abs(head_next - head))) if head_next.size else 0.0
            head = head_next
            result = replace(
                next_result,
                iterations=iteration,
                termination_reason=f"Picard iteration {iteration}",
            )
            omega_final = float(omega_used)
            records.append(
                _iteration_record(
                    mesh=mesh,
                    result=result,
                    iteration=iteration,
                    omega=omega_used,
                    Lstab=Lstab,
                    update_inf=update_inf,
                    lower=lower,
                    upper=upper,
                    linear_solve_status=linear_solve_status,
                    note=note,
                )
            )

            if result.residual_norm_inf <= float(options.picard_tolerance_residual_inf):
                stop_reason = "converged_target_residual"
                break
            if update_inf <= float(options.picard_tolerance_update_inf):
                stop_reason = "converged_update_only"
                break
            if note == "accepted_with_residual_growth":
                stop_reason = "stagnated"
                break

    picard_converged = float(result.residual_norm_inf) <= float(
        options.picard_tolerance_residual_inf
    )
    usable_as_initial_guess = float(result.residual_norm_inf) <= float(
        options.picard_usable_residual_inf
    )
    result = replace(
        result,
        converged=bool(picard_converged),
        termination_reason=f"Picard/L-scheme stop_reason={stop_reason}",
    )

    if bool(options.picard_final_vi_check):
        try:
            final_vi_result = _solve_strict_vi_obstacle(
                inputs,
                head_initial_guess_m=result.head_m,
            )
        except Exception as exc:  # noqa: BLE001 - diagnostic path
            final_vi_error = repr(exc)

    summary = _picard_summary(
        mesh=mesh,
        result=result,
        options=options,
        records=records,
        case_id=case_id,
        stop_reason=stop_reason,
        usable_as_initial_guess=usable_as_initial_guess,
        initial_residual=initial_residual,
        Lstab_final=Lstab_final,
        omega_final=omega_final,
        runtime_seconds=time.perf_counter() - start,
        final_vi_result=final_vi_result,
        final_vi_error=final_vi_error,
    )
    result = replace(result, diagnostics=summary)

    if bool(options.picard_output_diagnostics) and diagnostics_dir is not None:
        write_picard_lscheme_diagnostics(
            diagnostics_dir,
            mesh=mesh,
            result=result,
            options=options,
            records=records,
            case_id=case_id,
            summary=summary,
            inputs=inputs,
        )

    if final_vi_result is not None and final_vi_result.converged:
        merged = dict(final_vi_result.diagnostics or {})
        merged.update(summary)
        merged["picard_head_before_final_vi_m"] = _jsonable(result.head_m)
        return replace(
            final_vi_result,
            backend_name="bounded_picard_lscheme_then_strict_vi",
            diagnostics=merged,
            termination_reason=(
                "Picard initializer followed by strict PETSc SNESVI; "
                f"{final_vi_result.termination_reason}"
            ),
        )

    if bool(options.picard_final_vi_check) and bool(options.picard_fail_if_final_vi_fails):
        return replace(
            result,
            converged=False,
            termination_reason=(
                f"{result.termination_reason}; final strict VI check failed or was unavailable"
            ),
        )
    return result


def bounded_picard_vi_cycles(
    inputs: SteadySolveInputs,
    *,
    cycle_options: PicardViCycleOptions | None = None,
    diagnostics_dir: str | Path | None = None,
    case_id: str = "",
) -> RuntimeSolveResult:
    """Alternate strict Picard blocks and strict VI correction attempts."""
    options = cycle_options or PicardViCycleOptions()
    start = time.perf_counter()
    mesh = inputs.mesh
    prescribed = _prescribed_head_cells(inputs.prescribed_head_m_by_cell, n_cells=mesh.n_cells)
    lower, upper, prescribed_mask = _physical_bounds(mesh, prescribed)
    head = _clip_head(
        np.asarray(inputs.head_initial_guess_m, dtype=float).reshape(-1),
        lower=lower,
        upper=upper,
        project_bounds=True,
    )
    current_result = _strict_result_for_head(
        inputs,
        head,
        backend_name="bounded_picard_vi_cycles",
        iterations=0,
        termination_reason="Picard/VI cycle initial residual",
        extra_diagnostics={"method": "bounded_picard_vi_cycles"},
    )
    initial_residual = float(current_result.residual_norm_inf)
    records: list[PicardViCycleRecord] = []
    total_picard_iterations = 0
    last_vi_result: RuntimeSolveResult | None = None
    final_result: RuntimeSolveResult | None = None
    stop_reason = "max_cycles"

    for cycle in range(1, int(options.cycle_max) + 1):
        start_residual = float(current_result.residual_norm_inf)
        picard_options = replace(
            options.picard_options,
            picard_max_iterations=int(options.picard_steps_per_cycle),
            picard_final_vi_check=False,
            picard_fail_if_final_vi_fails=False,
            picard_output_diagnostics=False,
        )
        picard_inputs = replace(inputs, head_initial_guess_m=np.asarray(current_result.head_m))
        picard_result = bounded_picard_lscheme(
            picard_inputs,
            picard_options=picard_options,
            diagnostics_dir=None,
            case_id=case_id,
        )
        total_picard_iterations += int(picard_result.iterations)
        accepted_result = picard_result
        accepted_source = "picard"
        note = ""
        vi_result: RuntimeSolveResult | None = None
        vi_error = ""

        try:
            vi_result = _solve_strict_vi_obstacle(
                inputs,
                head_initial_guess_m=picard_result.head_m,
                max_iterations=int(options.vi_max_iterations_per_cycle),
            )
            last_vi_result = vi_result
        except Exception as exc:  # noqa: BLE001 - diagnostic path
            vi_error = repr(exc)

        if vi_result is not None and vi_result.converged:
            accepted_result = vi_result
            accepted_source = "vi_converged"
            final_result = vi_result
            stop_reason = "vi_converged"
        elif vi_result is not None and _accept_failed_vi_cycle_candidate(
            picard_result=picard_result,
            vi_result=vi_result,
            options=options,
        ):
            accepted_result = vi_result
            accepted_source = "failed_vi_accepted"
            note = "accepted_failed_vi_residual_reduction"
        elif vi_result is not None:
            note = "rejected_failed_vi"
        elif vi_error:
            note = "vi_exception"

        current_result = accepted_result
        records.append(
            _cycle_record(
                mesh=mesh,
                cycle=cycle,
                start_residual=start_residual,
                picard_result=picard_result,
                vi_result=vi_result,
                vi_error=vi_error,
                accepted_source=accepted_source,
                accepted_result=accepted_result,
                note=note,
            )
        )

        if final_result is not None:
            break
        if float(current_result.residual_norm_inf) <= float(inputs.options.tol_residual_inf):
            stop_reason = "accepted_state_reached_tolerance"
            break

    if (
        final_result is None
        and bool(options.final_vi_required)
        and last_vi_result is not current_result
    ):
        try:
            final_check = _solve_strict_vi_obstacle(
                inputs,
                head_initial_guess_m=current_result.head_m,
            )
            last_vi_result = final_check
            if final_check.converged:
                final_result = final_check
                stop_reason = "final_vi_converged"
        except Exception:
            pass

    result = final_result if final_result is not None else current_result
    summary = _cycle_summary(
        mesh=mesh,
        result=result,
        options=options,
        records=records,
        case_id=case_id,
        stop_reason=stop_reason,
        initial_residual=initial_residual,
        total_picard_iterations=total_picard_iterations,
        runtime_seconds=time.perf_counter() - start,
        last_vi_result=last_vi_result,
    )
    result = replace(
        result,
        backend_name=(
            "bounded_picard_vi_cycles_then_strict_vi"
            if result.converged
            else "bounded_picard_vi_cycles"
        ),
        iterations=(int(result.iterations) if result.converged else int(total_picard_iterations)),
        termination_reason=(
            f"Picard/VI cycles stop_reason={stop_reason}; {result.termination_reason}"
        ),
        diagnostics=summary,
    )
    if bool(options.output_diagnostics) and diagnostics_dir is not None:
        write_picard_vi_cycle_diagnostics(
            diagnostics_dir,
            mesh=mesh,
            result=result,
            options=options,
            records=records,
            summary=summary,
            inputs=inputs,
        )
    return result


def write_picard_lscheme_diagnostics(
    diagnostics_dir: str | Path,
    *,
    mesh: BoussinesqMesh,
    result: RuntimeSolveResult,
    options: PicardLschemeOptions,
    records: list[PicardIterationRecord],
    case_id: str,
    summary: dict[str, Any] | None = None,
    inputs: SteadySolveInputs | None = None,
) -> None:
    """Persist Picard JSON/CSV diagnostics."""
    out = Path(diagnostics_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = summary or _picard_summary(
        mesh=mesh,
        result=result,
        options=options,
        records=records,
        case_id=case_id,
        stop_reason=str((result.diagnostics or {}).get("picard_stop_reason", "")),
        usable_as_initial_guess=bool(
            (result.diagnostics or {}).get("usable_as_initial_guess", result.converged)
        ),
        initial_residual=float((result.diagnostics or {}).get("residual_initial", math.nan)),
        Lstab_final=float((result.diagnostics or {}).get("Lstab", math.nan)),
        omega_final=float((result.diagnostics or {}).get("omega_final", math.nan)),
        runtime_seconds=float((result.diagnostics or {}).get("runtime_seconds", math.nan)),
        final_vi_result=None,
        final_vi_error=None,
    )
    (out / PICARD_LSCHEME_SUMMARY_JSON).write_text(
        json.dumps(_jsonable(payload), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )

    with (out / PICARD_LSCHEME_ITERATIONS_CSV).open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(PicardIterationRecord.__dataclass_fields__)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(_jsonable(record.__dict__))

    rows = _final_cell_rows(
        mesh=mesh,
        result=result,
        top_n=int(options.picard_top_n_cells),
        inputs=inputs,
    )
    fieldnames = list(rows[0].keys()) if rows else _final_cell_fieldnames()
    with (out / PICARD_LSCHEME_FINAL_CELLS_CSV).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_picard_vi_cycle_diagnostics(
    diagnostics_dir: str | Path,
    *,
    mesh: BoussinesqMesh,
    result: RuntimeSolveResult,
    options: PicardViCycleOptions,
    records: list[PicardViCycleRecord],
    summary: dict[str, Any],
    inputs: SteadySolveInputs,
) -> None:
    """Persist Picard/VI cycle JSON/CSV diagnostics."""
    out = Path(diagnostics_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / PICARD_VI_CYCLE_SUMMARY_JSON).write_text(
        json.dumps(_jsonable(summary), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    with (out / PICARD_VI_CYCLES_CSV).open("w", newline="", encoding="utf-8") as handle:
        fieldnames = list(PicardViCycleRecord.__dataclass_fields__)
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow(_jsonable(record.__dict__))
    rows = _final_cell_rows(
        mesh=mesh,
        result=result,
        top_n=int(options.picard_options.picard_top_n_cells),
        inputs=inputs,
    )
    fieldnames = list(rows[0].keys()) if rows else _final_cell_fieldnames()
    with (out / PICARD_LSCHEME_FINAL_CELLS_CSV).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _accept_failed_vi_cycle_candidate(
    *,
    picard_result: RuntimeSolveResult,
    vi_result: RuntimeSolveResult,
    options: PicardViCycleOptions,
) -> bool:
    if bool(vi_result.converged):
        return True
    diagnostics = dict(vi_result.diagnostics or {})
    if bool(options.accept_failed_vi_if_bounds_ok):
        lower_violation = float(diagnostics.get("max_violation_lower_m", math.inf))
        upper_violation = float(diagnostics.get("max_violation_upper_m", math.inf))
        if lower_violation > 1.0e-8 or upper_violation > 1.0e-8:
            return False
    return float(vi_result.residual_norm_inf) <= float(
        options.accept_failed_vi_residual_factor
    ) * float(picard_result.residual_norm_inf)


def _cycle_record(
    *,
    mesh: BoussinesqMesh,
    cycle: int,
    start_residual: float,
    picard_result: RuntimeSolveResult,
    vi_result: RuntimeSolveResult | None,
    vi_error: str,
    accepted_source: str,
    accepted_result: RuntimeSolveResult,
    note: str,
) -> PicardViCycleRecord:
    diagnostics = dict(accepted_result.diagnostics or {})
    head = np.asarray(accepted_result.head_m, dtype=float).reshape(-1)
    lower = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1)
    upper = np.maximum(np.asarray(mesh.z_top_m, dtype=float).reshape(-1), lower)
    tol_h = 1.0e-9
    thickness = saturated_thickness_from_head(mesh, head)
    vi_iterations = 0 if vi_result is None else int(vi_result.iterations)
    vi_residual = math.nan if vi_result is None else float(vi_result.residual_norm_inf)
    return PicardViCycleRecord(
        cycle=int(cycle),
        start_residual_inf=float(start_residual),
        picard_iterations=int(picard_result.iterations),
        picard_residual_inf=float(picard_result.residual_norm_inf),
        picard_stop_reason=str((picard_result.diagnostics or {}).get("picard_stop_reason", "")),
        vi_attempted=vi_result is not None or bool(vi_error),
        vi_converged=False if vi_result is None else bool(vi_result.converged),
        vi_iterations=vi_iterations,
        vi_residual_inf=vi_residual,
        vi_termination_reason="" if vi_result is None else str(vi_result.termination_reason),
        vi_error=str(vi_error),
        accepted_source=str(accepted_source),
        accepted_residual_inf=float(accepted_result.residual_norm_inf),
        active_top_count=int(
            diagnostics.get("active_top_count", np.count_nonzero(head >= upper - tol_h))
        ),
        active_bottom_count=int(
            diagnostics.get("active_bottom_count", np.count_nonzero(head <= lower + tol_h))
        ),
        free_count=int(
            diagnostics.get(
                "free_count",
                np.count_nonzero((head > lower + tol_h) & (head < upper - tol_h)),
            )
        ),
        physically_dry_count=int(np.count_nonzero(thickness <= _DRY_THICKNESS_TOL_M)),
        note=str(note),
    )


def _cycle_summary(
    *,
    mesh: BoussinesqMesh,
    result: RuntimeSolveResult,
    options: PicardViCycleOptions,
    records: list[PicardViCycleRecord],
    case_id: str,
    stop_reason: str,
    initial_residual: float,
    total_picard_iterations: int,
    runtime_seconds: float,
    last_vi_result: RuntimeSolveResult | None,
) -> dict[str, Any]:
    head = np.asarray(result.head_m, dtype=float).reshape(-1)
    lower = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1)
    upper = np.maximum(np.asarray(mesh.z_top_m, dtype=float).reshape(-1), lower)
    thickness = saturated_thickness_from_head(mesh, head)
    transmissivity = np.asarray(mesh.hydraulic_conductivity_m_s, dtype=float) * thickness
    tol_h = 1.0e-9
    active_top = head >= upper - tol_h
    active_bottom = head <= lower + tol_h
    accepted_failed_vi_count = sum(
        1 for record in records if record.accepted_source == "failed_vi_accepted"
    )
    summary: dict[str, Any] = {
        "schema_version": 1,
        "method": "bounded_picard_vi_cycles",
        "strict_problem_definition": True,
        "case_id": str(case_id),
        "converged": bool(result.converged),
        "stop_reason": str(stop_reason),
        "cycle_count": len(records),
        "total_picard_iterations": int(total_picard_iterations),
        "vi_attempt_count": sum(1 for record in records if record.vi_attempted),
        "accepted_failed_vi_count": int(accepted_failed_vi_count),
        "initial_residual": float(initial_residual),
        "residual_final": float(result.residual_norm_inf),
        "final_vi_converged": bool(last_vi_result.converged) if last_vi_result else False,
        "final_vi_residual": (
            None if last_vi_result is None else float(last_vi_result.residual_norm_inf)
        ),
        "final_vi_iterations": None if last_vi_result is None else int(last_vi_result.iterations),
        "active_top_count": int(np.count_nonzero(active_top)),
        "active_bottom_count": int(np.count_nonzero(active_bottom)),
        "free_count": int(np.count_nonzero(~(active_top | active_bottom))),
        "cells_physically_dry_count": int(np.count_nonzero(thickness <= _DRY_THICKNESS_TOL_M)),
        "h_min": float(np.min(head)) if head.size else math.nan,
        "h_max": float(np.max(head)) if head.size else math.nan,
        "physical_saturated_thickness_quantiles": _quantiles(thickness),
        "transmissivity_quantiles": _quantiles(transmissivity),
        "runtime_seconds": float(runtime_seconds),
        "cycle_options": _jsonable(options.__dict__),
    }
    if records:
        summary["last_cycle"] = _jsonable(records[-1].__dict__)
    return summary


def _accept_relaxed_candidate(
    *,
    mesh: BoussinesqMesh,
    head_old: np.ndarray,
    trial: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    prescribed_mask: np.ndarray,
    inputs: SteadySolveInputs,
    prescribed_head_m_by_cell: np.ndarray,
    options: PicardLschemeOptions,
    previous_projected_residual_inf: float,
) -> tuple[tuple[np.ndarray, RuntimeSolveResult], float, str]:
    omega = float(options.picard_relaxation_omega)
    omega_min = max(float(options.picard_omega_min), 0.0)
    growth_factor = max(float(options.picard_residual_growth_factor), 1.0)
    best: tuple[np.ndarray, RuntimeSolveResult] | None = None
    best_residual = math.inf
    best_omega = omega
    note = "accepted"

    while omega >= omega_min - 1.0e-15:
        candidate = (1.0 - omega) * np.asarray(head_old, dtype=float) + omega * np.asarray(
            trial, dtype=float
        )
        candidate = _clip_head(
            candidate,
            lower=lower,
            upper=upper,
            project_bounds=bool(options.picard_project_bounds),
        )
        raw = _assemble_strict_steady_residual(
            mesh,
            candidate,
            recharge_rate_m_s=inputs.recharge_rate_m_s,
            well_flux_m3_s=inputs.well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        )
        candidate_result = _runtime_result_from_raw_assembly(
            mesh=mesh,
            raw_assembly=raw,
            head=candidate,
            lower=lower,
            upper=upper,
            prescribed_mask=prescribed_mask,
            inputs=inputs,
            backend_name="bounded_picard_lscheme",
            iterations=0,
            termination_reason="Picard candidate",
            extra_diagnostics={"method": "bounded_picard_lscheme"},
        )
        residual = float(candidate_result.residual_norm_inf)
        if residual < best_residual:
            best = (candidate, candidate_result)
            best_residual = residual
            best_omega = omega
        if residual <= growth_factor * float(previous_projected_residual_inf):
            return (candidate, candidate_result), omega, note
        omega *= 0.5
        note = "omega_halved"

    if best is None:
        raise RuntimeError("Picard relaxation did not produce a candidate.")
    return best, best_omega, "accepted_with_residual_growth"


def _picard_linear_system(
    mesh: BoussinesqMesh,
    *,
    head_old: np.ndarray,
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
    prescribed_head_m_by_cell: np.ndarray,
    prescribed_mask: np.ndarray,
    drainage_conductance_m2_s: np.ndarray | float | None,
    lscheme_L: float | str,
):
    """Assemble ``A h_new = rhs`` with strict lagged physical transmissivity."""
    try:
        from scipy import sparse
    except Exception as exc:  # pragma: no cover - depends on optional dependency state
        raise RuntimeError("stationary_picard_lscheme requires scipy.sparse.") from exc

    n_cells = int(mesh.n_cells)
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []
    rhs = np.asarray(mesh.cell_area_m2, dtype=float) * as_cell_vector(
        recharge_rate_m_s, n_cells=n_cells, label="recharge_rate_m_s"
    ) + as_cell_vector(well_flux_m3_s, n_cells=n_cells, label="well_flux_m3_s")
    prescribed = np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)
    prescribed_mask = np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    head_old = np.asarray(head_old, dtype=float).reshape(-1)

    thickness = saturated_thickness_from_head(mesh, head_old)
    base_diag = np.zeros(n_cells, dtype=float)
    for edge_index in range(int(mesh.n_edges)):
        cell_a = int(mesh.edge_cell_a[edge_index])
        cell_b = int(mesh.edge_cell_b[edge_index])
        if cell_b < 0:
            continue
        tau = _lagged_internal_tau(mesh, thickness=thickness, edge_index=edge_index)
        if tau == 0.0:
            continue
        if not prescribed_mask[cell_a]:
            rows.extend([cell_a, cell_a])
            cols.extend([cell_a, cell_b])
            data.extend([tau, -tau])
            base_diag[cell_a] += abs(tau)
        if not prescribed_mask[cell_b]:
            rows.extend([cell_b, cell_b])
            cols.extend([cell_b, cell_a])
            data.extend([tau, -tau])
            base_diag[cell_b] += abs(tau)

    conductance = _strict_drainage_conductance(
        mesh,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    active_drainage = head_old > np.asarray(mesh.z_top_m, dtype=float).reshape(-1)
    drainage_diag = np.where(active_drainage, conductance, 0.0)
    for cell in np.flatnonzero((drainage_diag > 0.0) & ~prescribed_mask):
        coeff = float(drainage_diag[int(cell)])
        rows.append(int(cell))
        cols.append(int(cell))
        data.append(coeff)
        rhs[int(cell)] += coeff * float(mesh.z_top_m[int(cell)])
        base_diag[int(cell)] += coeff

    Lstab = _resolve_lscheme_L(mesh, base_diag=base_diag, lscheme_L=lscheme_L)
    areas = np.asarray(mesh.cell_area_m2, dtype=float).reshape(-1)
    for cell in range(n_cells):
        if prescribed_mask[cell]:
            continue
        coeff = float(Lstab) * max(float(areas[cell]), 0.0)
        rows.append(cell)
        cols.append(cell)
        data.append(coeff)
        rhs[cell] += coeff * float(head_old[cell])

    for cell in np.flatnonzero(prescribed_mask):
        rows.append(int(cell))
        cols.append(int(cell))
        data.append(1.0)
        rhs[int(cell)] = float(prescribed[int(cell)])

    matrix = sparse.coo_matrix((data, (rows, cols)), shape=(n_cells, n_cells)).tocsr()
    return matrix, rhs, float(Lstab)


def _solve_sparse_system(matrix, rhs: np.ndarray) -> np.ndarray:
    try:
        from scipy.sparse.linalg import spsolve
    except Exception as exc:  # pragma: no cover - depends on optional dependency state
        raise RuntimeError("stationary_picard_lscheme requires scipy.sparse.linalg.") from exc
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return np.asarray(spsolve(matrix, np.asarray(rhs, dtype=float)), dtype=float).reshape(-1)


def _lagged_internal_tau(
    mesh: BoussinesqMesh,
    *,
    thickness: np.ndarray,
    edge_index: int,
) -> float:
    cell_a = int(mesh.edge_cell_a[edge_index])
    cell_b = int(mesh.edge_cell_b[edge_index])
    if cell_b < 0:
        return 0.0
    conductivity_edge = harmonic_conductivity(
        float(mesh.hydraulic_conductivity_m_s[cell_a]),
        float(mesh.hydraulic_conductivity_m_s[cell_b]),
    )
    thickness_edge = 0.5 * (float(thickness[cell_a]) + float(thickness[cell_b]))
    distance = max(float(mesh.edge_distance_m[edge_index]), _MIN_DISTANCE_M)
    return (
        max(conductivity_edge, 0.0)
        * max(thickness_edge, 0.0)
        * float(mesh.edge_length_m[edge_index])
        / distance
    )


def _resolve_lscheme_L(
    mesh: BoussinesqMesh,
    *,
    base_diag: np.ndarray,
    lscheme_L: float | str,
) -> float:
    if isinstance(lscheme_L, str):
        if lscheme_L.strip().lower() != "auto":
            return float(lscheme_L)
        areas = np.asarray(mesh.cell_area_m2, dtype=float).reshape(-1)
        scaled = np.divide(
            np.asarray(base_diag, dtype=float),
            areas,
            out=np.zeros_like(np.asarray(base_diag, dtype=float)),
            where=areas > 0.0,
        )
        positive = scaled[np.isfinite(scaled) & (scaled > 0.0)]
        if positive.size == 0:
            return 1.0e-10
        return max(float(np.quantile(positive, 0.75)), 1.0e-10)
    return max(float(lscheme_L), 0.0)


def _assemble_strict_steady_residual(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    recharge_rate_m_s: np.ndarray | float | None = None,
    well_flux_m3_s: np.ndarray | float | None = None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
) -> BoussinesqAssembly:
    """Assemble the strict steady residual with no artificial thickness floor."""
    n_cells = int(mesh.n_cells)
    head = np.asarray(head_m, dtype=float).reshape(-1).copy()
    if head.size != n_cells:
        raise ValueError(f"head_m length must match mesh.n_cells ({head.size} != {n_cells}).")
    prescribed = _prescribed_head_cells(prescribed_head_m_by_cell, n_cells=n_cells)
    prescribed_mask = np.isfinite(prescribed)
    if np.any(prescribed_mask):
        head[prescribed_mask] = prescribed[prescribed_mask]

    thickness = saturated_thickness_from_head(mesh, head)
    transmissivity = np.asarray(mesh.hydraulic_conductivity_m_s, dtype=float) * thickness
    internal_flux = internal_edge_flux_from_head(mesh, head)
    internal_residual = accumulate_internal_flux_residual(mesh, internal_flux)
    recharge = as_cell_vector(recharge_rate_m_s, n_cells=n_cells, label="recharge_rate_m_s")
    well_flux = as_cell_vector(well_flux_m3_s, n_cells=n_cells, label="well_flux_m3_s")
    drainage = _strict_drainage_flux(
        mesh,
        head,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    zero_cells = np.zeros(n_cells, dtype=float)
    zero_edges = np.zeros(int(mesh.n_edges), dtype=float)
    raw_residual = (
        internal_residual
        + drainage
        - np.asarray(mesh.cell_area_m2, dtype=float) * recharge
        - well_flux
    )
    (
        solver_residual,
        prescribed_flux,
        head_constraint,
        flow_residual,
    ) = finalize_boundary_constrained_residual(
        head_m=head,
        raw_residual_m3_s=raw_residual,
        prescribed_head_m_by_cell=prescribed,
    )
    return BoussinesqAssembly(
        head_m=head,
        saturated_thickness_m=thickness,
        transmissivity_m2_s=transmissivity,
        recharge_rate_m_s=recharge,
        well_flux_m3_s=well_flux,
        saturation_excess_rate_m_s=zero_cells.copy(),
        internal_edge_flux_m3_s=internal_flux,
        prescribed_head_flux_m3_s=prescribed_flux,
        prescribed_head_m_by_cell=prescribed,
        head_constraint_residual_m=head_constraint,
        boundary_edge_flux_m3_s=zero_edges,
        drainage_flux_m3_s=drainage,
        flow_residual_m3_s=flow_residual,
        solver_residual=solver_residual,
        residual_m3_s=flow_residual,
        dry_deficit_rate_m_s=zero_cells.copy(),
    )


def _strict_drainage_conductance(
    mesh: BoussinesqMesh,
    *,
    drainage_conductance_m2_s: np.ndarray | float | None,
) -> np.ndarray:
    """Return only explicitly positive drainage conductance values."""
    if drainage_conductance_m2_s is None:
        return np.zeros(int(mesh.n_cells), dtype=float)
    values = as_cell_vector(
        drainage_conductance_m2_s,
        n_cells=int(mesh.n_cells),
        label="drainage_conductance_m2_s",
    )
    return np.where(values > 0.0, values, 0.0)


def _strict_drainage_flux(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    drainage_conductance_m2_s: np.ndarray | float | None,
) -> np.ndarray:
    conductance = _strict_drainage_conductance(
        mesh,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    return conductance * np.maximum(np.asarray(head_m, dtype=float) - mesh.z_top_m, 0.0)


def _solve_strict_vi_obstacle(
    inputs: SteadySolveInputs,
    *,
    head_initial_guess_m: np.ndarray,
    max_iterations: int | None = None,
) -> RuntimeSolveResult:
    """Run a strict PETSc SNESVI check with physical bounds and strict residual."""
    PETSc = _require_petsc()
    petsc_index_dtype = np.dtype(PETSc.IntType)
    mesh = inputs.mesh
    n_cells = int(mesh.n_cells)
    prescribed = _prescribed_head_cells(inputs.prescribed_head_m_by_cell, n_cells=n_cells)
    lower, upper, prescribed_mask = _physical_bounds(mesh, prescribed)
    head0 = _clip_head(
        np.asarray(head_initial_guess_m, dtype=float).reshape(-1),
        lower=lower,
        upper=upper,
        project_bounds=True,
    )

    solution = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    residual_template = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    lower_vec = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    upper_vec = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    jacobian = PETSc.Mat().createAIJ([n_cells, n_cells], nnz=12, comm=PETSc.COMM_SELF)
    jacobian.setUp()
    jacobian.setOption(PETSc.Mat.Option.NEW_NONZERO_ALLOCATION_ERR, False)
    np.asarray(solution.getArray(), dtype=float)[:] = head0
    np.asarray(lower_vec.getArray(), dtype=float)[:] = lower
    np.asarray(upper_vec.getArray(), dtype=float)[:] = upper

    current_assembly = _assemble_strict_steady_residual(
        mesh,
        head0,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
    )

    def _residual(_snes, state_vec, residual_vec) -> None:
        nonlocal current_assembly
        head = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        current_assembly = _assemble_strict_steady_residual(
            mesh,
            head,
            recharge_rate_m_s=inputs.recharge_rate_m_s,
            well_flux_m3_s=inputs.well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        )
        np.asarray(residual_vec.getArray(), dtype=float)[:] = np.asarray(
            current_assembly.solver_residual,
            dtype=float,
        )

    def _jacobian(_snes, state_vec, jac, preconditioner) -> None:
        head = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        data, row_indices, col_indices = _strict_jacobian_triplets(
            mesh,
            head,
            prescribed_head_m_by_cell=prescribed,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        )
        indptr, indices, values = _coo_to_csr(
            n_rows=n_cells,
            n_cols=n_cells,
            row_indices=row_indices,
            col_indices=col_indices,
            data=data,
            index_dtype=petsc_index_dtype,
        )
        for matrix in (jac,) if jac is preconditioner else (jac, preconditioner):
            matrix.zeroEntries()
            if values.size != 0:
                matrix.setValuesCSR(indptr, indices, values)
            matrix.assemble()

    snes = PETSc.SNES().create(comm=PETSc.COMM_SELF)
    snes.setFunction(_residual, residual_template)
    snes.setJacobian(_jacobian, jacobian, jacobian)
    snes.setVariableBounds(lower_vec, upper_vec)
    petsc_vi_obstacle._configure_vi_snes(
        PETSc,
        snes,
        tol_residual_inf=float(inputs.options.tol_residual_inf),
        max_iterations=int(
            inputs.options.max_iterations if max_iterations is None else max_iterations
        ),
    )
    snes.solve(None, solution)
    head = np.asarray(solution.getArray(readonly=True), dtype=float).copy()
    raw_assembly = _assemble_strict_steady_residual(
        mesh,
        head,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
    )
    base_result = _runtime_result_from_raw_assembly(
        mesh=mesh,
        raw_assembly=raw_assembly,
        head=head,
        lower=lower,
        upper=upper,
        prescribed_mask=prescribed_mask,
        inputs=inputs,
        backend_name="strict_petsc_vi_obstacle",
        iterations=int(snes.getIterationNumber()),
        termination_reason="strict PETSc SNESVI check",
        extra_diagnostics=_strict_snes_diagnostics(
            snes,
            raw_assembly=raw_assembly,
            head=head,
            lower=lower,
            upper=upper,
            prescribed_mask=prescribed_mask,
            inputs=inputs,
        ),
    )
    reason = int(snes.getConvergedReason())
    diagnostics = dict(base_result.diagnostics or {})
    accepted = petsc_vi_obstacle._accept_failed_snes_by_projected_tolerance(
        converged_reason=reason,
        residual_norm_inf_value=float(base_result.residual_norm_inf),
        tol_residual_inf=float(inputs.options.tol_residual_inf),
        max_violation_lower_m=float(diagnostics.get("max_violation_lower_m", math.inf)),
        max_violation_upper_m=float(diagnostics.get("max_violation_upper_m", math.inf)),
        tol_h=_obstacle_tolerance(inputs),
    )
    reason_label = _snes_reason_label(reason)
    termination = (
        f"strict PETSc SNESVI converged reason {reason} ({reason_label})"
        if reason > 0
        else f"strict PETSc SNESVI failed reason {reason} ({reason_label})"
    )
    if accepted:
        termination = (
            f"{termination}; accepted because projected_vi_residual_inf="
            f"{base_result.residual_norm_inf:.3e} <= tol_residual_inf="
            f"{float(inputs.options.tol_residual_inf):.3e}"
        )
    converged, termination = apply_residual_tolerance(
        success=reason > 0 or accepted,
        residual_norm_inf_value=float(base_result.residual_norm_inf),
        tol_residual_inf=float(inputs.options.tol_residual_inf),
        termination_reason=termination,
        residual_label="projected_vi_residual_inf",
    )
    diagnostics["accepted_by_projected_tolerance"] = bool(accepted)
    return replace(
        base_result,
        converged=bool(converged),
        termination_reason=termination,
        diagnostics=diagnostics,
    )


def _strict_snes_diagnostics(
    snes,
    *,
    raw_assembly: BoussinesqAssembly,
    head: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    prescribed_mask: np.ndarray,
    inputs: SteadySolveInputs,
) -> dict[str, Any]:
    reason = int(snes.getConvergedReason())
    tol_h = _obstacle_tolerance(inputs)
    projected = petsc_vi_obstacle._projected_vi_residual(
        residual=np.asarray(raw_assembly.solver_residual, dtype=float),
        head_m=head,
        lower_m=lower,
        upper_m=upper,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    diagnostics: dict[str, Any] = {
        "snes_converged_reason": reason,
        "snes_converged_reason_label": _snes_reason_label(reason),
        "snes_iterations": int(snes.getIterationNumber()),
        "projected_vi_residual_norm_inf": residual_norm_inf(projected),
        "free_residual_norm_inf": _free_residual_norm(
            residual=np.asarray(raw_assembly.flow_residual_m3_s, dtype=float),
            head=head,
            lower=lower,
            upper=upper,
            prescribed_mask=prescribed_mask,
            tol_h=tol_h,
        ),
        "strict_problem_definition": True,
    }
    try:
        diagnostics["petsc_function_norm"] = float(snes.getFunctionNorm())
    except Exception:
        diagnostics["petsc_function_norm"] = None
    return diagnostics


def _strict_jacobian_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    head = np.asarray(head_m, dtype=float).reshape(-1)
    n_cells = int(mesh.n_cells)
    prescribed = _prescribed_head_cells(prescribed_head_m_by_cell, n_cells=n_cells)
    prescribed_mask = np.isfinite(prescribed)
    thickness, derivative = _strict_thickness_and_derivative(mesh, head)
    rows: list[int] = []
    cols: list[int] = []
    data: list[float] = []

    for edge_index in range(int(mesh.n_edges)):
        cell_a = int(mesh.edge_cell_a[edge_index])
        cell_b = int(mesh.edge_cell_b[edge_index])
        if cell_b < 0:
            continue
        conductivity_edge = harmonic_conductivity(
            float(mesh.hydraulic_conductivity_m_s[cell_a]),
            float(mesh.hydraulic_conductivity_m_s[cell_b]),
        )
        distance = max(float(mesh.edge_distance_m[edge_index]), _MIN_DISTANCE_M)
        factor = max(conductivity_edge, 0.0) * float(mesh.edge_length_m[edge_index]) / distance
        tau = factor * 0.5 * (float(thickness[cell_a]) + float(thickness[cell_b]))
        delta = float(head[cell_b] - head[cell_a])
        dtau_da = factor * 0.5 * float(derivative[cell_a])
        dtau_db = factor * 0.5 * float(derivative[cell_b])
        dq_da = tau - dtau_da * delta
        dq_db = -tau - dtau_db * delta
        if not prescribed_mask[cell_a]:
            rows.extend([cell_a, cell_a])
            cols.extend([cell_a, cell_b])
            data.extend([dq_da, dq_db])
        if not prescribed_mask[cell_b]:
            rows.extend([cell_b, cell_b])
            cols.extend([cell_a, cell_b])
            data.extend([-dq_da, -dq_db])

    conductance = _strict_drainage_conductance(
        mesh,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    active_drainage = head > np.asarray(mesh.z_top_m, dtype=float).reshape(-1)
    for cell in np.flatnonzero((conductance > 0.0) & active_drainage & ~prescribed_mask):
        rows.append(int(cell))
        cols.append(int(cell))
        data.append(float(conductance[int(cell)]))

    for cell in np.flatnonzero(prescribed_mask):
        rows.append(int(cell))
        cols.append(int(cell))
        data.append(1.0)

    return (
        np.asarray(data, dtype=float),
        np.asarray(rows, dtype=int),
        np.asarray(cols, dtype=int),
    )


def _strict_thickness_and_derivative(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    head = np.asarray(head_m, dtype=float).reshape(-1)
    bottom = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1)
    top = np.asarray(mesh.z_top_m, dtype=float).reshape(-1)
    max_thickness = np.maximum(top - bottom, 0.0)
    raw = head - bottom
    thickness = np.clip(raw, 0.0, max_thickness)
    derivative = np.where((raw > 0.0) & (raw < max_thickness), 1.0, 0.0)
    return thickness, derivative


def _runtime_result_from_raw_assembly(
    *,
    mesh: BoussinesqMesh,
    raw_assembly: BoussinesqAssembly,
    head: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    prescribed_mask: np.ndarray,
    inputs: SteadySolveInputs,
    backend_name: str,
    iterations: int,
    termination_reason: str,
    extra_diagnostics: dict[str, Any] | None = None,
) -> RuntimeSolveResult:
    tol_h = _obstacle_tolerance(inputs)
    reacted_assembly, reaction_diagnostics = petsc_vi_obstacle._reconstruct_obstacle_reactions(
        mesh=mesh,
        assembly=raw_assembly,
        head_m=head,
        physical_lower_m=lower,
        physical_upper_m=upper,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    projected = petsc_vi_obstacle._projected_vi_residual(
        residual=np.asarray(raw_assembly.solver_residual, dtype=float),
        head_m=head,
        lower_m=lower,
        upper_m=upper,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    residual_norm = residual_norm_inf(projected)
    max_lower = float(np.max(np.maximum(lower - np.asarray(head, dtype=float), 0.0)))
    max_upper = float(np.max(np.maximum(np.asarray(head, dtype=float) - upper, 0.0)))
    diagnostics: dict[str, Any] = {
        "projected_vi_residual_norm_inf": residual_norm,
        "free_residual_norm_inf": _free_residual_norm(
            residual=np.asarray(raw_assembly.flow_residual_m3_s, dtype=float),
            head=head,
            lower=lower,
            upper=upper,
            prescribed_mask=prescribed_mask,
            tol_h=tol_h,
        ),
        "max_violation_lower_m": max_lower,
        "max_violation_upper_m": max_upper,
        "strict_problem_definition": True,
    }
    diagnostics.update(reaction_diagnostics)
    if extra_diagnostics:
        diagnostics.update(extra_diagnostics)
    return build_runtime_result(
        head_m=np.asarray(head, dtype=float),
        assembly=reacted_assembly,
        converged=residual_norm <= float(inputs.options.tol_residual_inf),
        iterations=int(iterations),
        residual_norm_inf_value=residual_norm,
        backend_name=backend_name,
        termination_reason=termination_reason,
        diagnostics=diagnostics,
    )


def _strict_result_for_head(
    inputs: SteadySolveInputs,
    head_m: np.ndarray,
    *,
    backend_name: str,
    iterations: int,
    termination_reason: str,
    extra_diagnostics: dict[str, Any] | None = None,
) -> RuntimeSolveResult:
    mesh = inputs.mesh
    prescribed = _prescribed_head_cells(inputs.prescribed_head_m_by_cell, n_cells=mesh.n_cells)
    lower, upper, prescribed_mask = _physical_bounds(mesh, prescribed)
    head = _clip_head(
        np.asarray(head_m, dtype=float).reshape(-1),
        lower=lower,
        upper=upper,
        project_bounds=True,
    )
    raw = _assemble_strict_steady_residual(
        mesh,
        head,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
    )
    return _runtime_result_from_raw_assembly(
        mesh=mesh,
        raw_assembly=raw,
        head=head,
        lower=lower,
        upper=upper,
        prescribed_mask=prescribed_mask,
        inputs=inputs,
        backend_name=backend_name,
        iterations=iterations,
        termination_reason=termination_reason,
        extra_diagnostics=extra_diagnostics,
    )


def _physical_bounds(
    mesh: BoussinesqMesh,
    prescribed_head_m_by_cell: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lower = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1).copy()
    upper = np.maximum(np.asarray(mesh.z_top_m, dtype=float).reshape(-1), lower)
    prescribed = np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)
    prescribed_mask = np.isfinite(prescribed)
    if np.any(prescribed_mask):
        pinned = np.clip(
            prescribed[prescribed_mask], lower[prescribed_mask], upper[prescribed_mask]
        )
        lower[prescribed_mask] = pinned
        upper[prescribed_mask] = pinned
    return lower, upper, prescribed_mask


def _clip_head(
    head_m: np.ndarray,
    *,
    lower: np.ndarray,
    upper: np.ndarray,
    project_bounds: bool,
) -> np.ndarray:
    head = np.asarray(head_m, dtype=float).reshape(-1).copy()
    if head.size != np.asarray(lower).size:
        raise ValueError(
            f"head_m length must match bounds ({int(head.size)} != {int(np.asarray(lower).size)})."
        )
    if not bool(project_bounds):
        return head
    return np.clip(head, np.asarray(lower, dtype=float), np.asarray(upper, dtype=float))


def _prescribed_head_cells(
    prescribed_head_m_by_cell: np.ndarray | None,
    *,
    n_cells: int,
) -> np.ndarray:
    return as_prescribed_head_cell_vector(
        prescribed_head_m_by_cell,
        n_cells=int(n_cells),
        label="prescribed_head_m_by_cell",
    )


def _obstacle_tolerance(inputs: SteadySolveInputs) -> float:
    return max(1.0e-9, 10.0 * float(inputs.options.tol_state_update_inf))


def _free_residual_norm(
    *,
    residual: np.ndarray,
    head: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    prescribed_mask: np.ndarray,
    tol_h: float,
) -> float:
    head = np.asarray(head, dtype=float).reshape(-1)
    free = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    interior = free & (head > lower + float(tol_h)) & (head < upper - float(tol_h))
    if not np.any(interior):
        return 0.0
    return residual_norm_inf(np.asarray(residual, dtype=float).reshape(-1)[interior])


def _iteration_record(
    *,
    mesh: BoussinesqMesh,
    result: RuntimeSolveResult,
    iteration: int,
    omega: float,
    Lstab: float,
    update_inf: float,
    lower: np.ndarray,
    upper: np.ndarray,
    linear_solve_status: str,
    note: str,
) -> PicardIterationRecord:
    head = np.asarray(result.head_m, dtype=float)
    tol_h = max(1.0e-9, 10.0 * 1.0e-12)
    free_mask = _free_mask_from_bounds(head=head, lower=lower, upper=upper, tol_h=tol_h)
    thickness = saturated_thickness_from_head(mesh, head)
    return PicardIterationRecord(
        iteration=int(iteration),
        omega=float(omega),
        Lstab=float(Lstab),
        residual_inf=float(result.residual_norm_inf),
        projected_residual_inf=float(
            (result.diagnostics or {}).get(
                "projected_vi_residual_norm_inf",
                result.residual_norm_inf,
            )
        ),
        update_inf=float(update_inf),
        active_top_count=int(np.count_nonzero(head >= upper - tol_h)),
        active_bottom_count=int(np.count_nonzero(head <= lower + tol_h)),
        free_count=int(np.count_nonzero(free_mask)),
        physically_dry_count=int(np.count_nonzero(thickness <= _DRY_THICKNESS_TOL_M)),
        max_lower_violation=float(np.max(np.maximum(lower - head, 0.0))),
        max_upper_violation=float(np.max(np.maximum(head - upper, 0.0))),
        linear_solve_status=str(linear_solve_status),
        note=str(note),
    )


def _picard_summary(
    *,
    mesh: BoussinesqMesh,
    result: RuntimeSolveResult,
    options: PicardLschemeOptions,
    records: list[PicardIterationRecord],
    case_id: str,
    stop_reason: str,
    usable_as_initial_guess: bool,
    initial_residual: float,
    Lstab_final: float,
    omega_final: float,
    runtime_seconds: float,
    final_vi_result: RuntimeSolveResult | None,
    final_vi_error: str | None,
) -> dict[str, Any]:
    head = np.asarray(result.head_m, dtype=float).reshape(-1)
    lower = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1)
    upper = np.maximum(np.asarray(mesh.z_top_m, dtype=float).reshape(-1), lower)
    thickness = saturated_thickness_from_head(mesh, head)
    transmissivity = np.asarray(mesh.hydraulic_conductivity_m_s, dtype=float) * thickness
    tol_h = 1.0e-9
    active_top = head >= upper - tol_h
    active_bottom = head <= lower + tol_h
    free_count = int(np.count_nonzero(~(active_top | active_bottom)))
    summary: dict[str, Any] = {
        "schema_version": 1,
        "method": "bounded_picard_lscheme",
        "strict_problem_definition": True,
        "case_id": str(case_id),
        "converged": bool(result.converged),
        "picard_converged": bool(result.converged),
        "stop_reason": str(stop_reason),
        "picard_stop_reason": str(stop_reason),
        "usable_as_initial_guess": bool(usable_as_initial_guess),
        "final_vi_check_enabled": bool(options.picard_final_vi_check),
        "final_vi_converged": bool(final_vi_result.converged) if final_vi_result else False,
        "final_vi_residual": (
            None if final_vi_result is None else float(final_vi_result.residual_norm_inf)
        ),
        "final_vi_error": final_vi_error,
        "n_iterations": int(result.iterations),
        "Lstab": float(Lstab_final),
        "omega_initial": float(options.picard_relaxation_omega),
        "omega_final": float(omega_final),
        "residual_initial": float(initial_residual),
        "residual_final": float(result.residual_norm_inf),
        "update_inf_final": 0.0 if not records else float(records[-1].update_inf),
        "active_top_count": int(np.count_nonzero(active_top)),
        "active_bottom_count": int(np.count_nonzero(active_bottom)),
        "free_count": free_count,
        "cells_physically_dry_count": int(np.count_nonzero(thickness <= _DRY_THICKNESS_TOL_M)),
        "max_lower_violation": float(np.max(np.maximum(lower - head, 0.0))),
        "max_upper_violation": float(np.max(np.maximum(head - upper, 0.0))),
        "h_min": float(np.min(head)) if head.size else math.nan,
        "h_max": float(np.max(head)) if head.size else math.nan,
        "physical_saturated_thickness_quantiles": _quantiles(thickness),
        "transmissivity_quantiles": _quantiles(transmissivity),
        "runtime_seconds": float(runtime_seconds),
        "picard_options": _jsonable(options.__dict__),
    }
    if final_vi_result is not None:
        summary["final_vi_iterations"] = int(final_vi_result.iterations)
        summary["final_vi_termination_reason"] = str(final_vi_result.termination_reason)
    return summary


def _final_cell_rows(
    *,
    mesh: BoussinesqMesh,
    result: RuntimeSolveResult,
    top_n: int,
    inputs: SteadySolveInputs | None,
) -> list[dict[str, Any]]:
    head = np.asarray(result.head_m, dtype=float).reshape(-1)
    prescribed = (
        _prescribed_head_cells(inputs.prescribed_head_m_by_cell, n_cells=mesh.n_cells)
        if inputs is not None
        else _prescribed_head_cells(None, n_cells=mesh.n_cells)
    )
    lower, upper, prescribed_mask = _physical_bounds(mesh, prescribed)
    raw = (
        _assemble_strict_steady_residual(
            mesh,
            head,
            recharge_rate_m_s=None if inputs is None else inputs.recharge_rate_m_s,
            well_flux_m3_s=None if inputs is None else inputs.well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed,
            drainage_conductance_m2_s=None if inputs is None else inputs.drainage_conductance_m2_s,
        )
        if inputs is not None
        else result.assembly
    )
    tol_h = 1.0e-9
    projected = petsc_vi_obstacle._projected_vi_residual(
        residual=np.asarray(raw.solver_residual, dtype=float),
        head_m=head,
        lower_m=lower,
        upper_m=upper,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    residual = np.asarray(raw.flow_residual_m3_s, dtype=float).reshape(-1)
    thickness = saturated_thickness_from_head(mesh, head)
    transmissivity = np.asarray(mesh.hydraulic_conductivity_m_s, dtype=float) * thickness
    drainage = np.asarray(raw.drainage_flux_m3_s, dtype=float).reshape(-1)
    order = np.argsort(-np.abs(projected))
    if int(top_n) > 0:
        order = order[: int(top_n)]
    neighbor_count = _neighbor_counts(mesh)
    rows: list[dict[str, Any]] = []
    for cell in order:
        i = int(cell)
        rows.append(
            {
                "cell_id": _cell_id(mesh, i),
                "x": _cell_coord(mesh, i, ("cell_centroid_x_m", "cell_x_m", "x")),
                "y": _cell_coord(mesh, i, ("cell_centroid_y_m", "cell_y_m", "y")),
                "area": float(mesh.cell_area_m2[i]),
                "K": float(mesh.hydraulic_conductivity_m_s[i]),
                "z_bottom": float(mesh.z_bottom_m[i]),
                "z_top": float(mesh.z_top_m[i]),
                "h": float(head[i]),
                "h_minus_z_top": float(head[i] - mesh.z_top_m[i]),
                "h_minus_z_bottom": float(head[i] - mesh.z_bottom_m[i]),
                "physical_saturated_thickness": float(thickness[i]),
                "transmissivity": float(transmissivity[i]),
                "residual": float(residual[i]),
                "projected_residual": float(projected[i]),
                "active_state": _active_state(
                    head=float(head[i]),
                    lower=float(lower[i]),
                    upper=float(upper[i]),
                    prescribed=bool(prescribed_mask[i]),
                    tol_h=tol_h,
                ),
                "drainage_rate": float(drainage[i]),
                "n_neighbors": int(neighbor_count[i]),
            }
        )
    return rows


def _final_cell_fieldnames() -> list[str]:
    return [
        "cell_id",
        "x",
        "y",
        "area",
        "K",
        "z_bottom",
        "z_top",
        "h",
        "h_minus_z_top",
        "h_minus_z_bottom",
        "physical_saturated_thickness",
        "transmissivity",
        "residual",
        "projected_residual",
        "active_state",
        "drainage_rate",
        "n_neighbors",
    ]


def _active_state(
    *,
    head: float,
    lower: float,
    upper: float,
    prescribed: bool,
    tol_h: float,
) -> str:
    if prescribed:
        return "prescribed"
    if head <= lower + tol_h:
        return "bottom"
    if head >= upper - tol_h:
        return "top"
    return "free"


def _free_mask_from_bounds(
    *,
    head: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    tol_h: float,
) -> np.ndarray:
    return (np.asarray(head) > np.asarray(lower) + tol_h) & (
        np.asarray(head) < np.asarray(upper) - tol_h
    )


def _neighbor_counts(mesh: BoussinesqMesh) -> np.ndarray:
    counts = np.zeros(int(mesh.n_cells), dtype=int)
    for edge_index in range(int(mesh.n_edges)):
        cell_a = int(mesh.edge_cell_a[edge_index])
        cell_b = int(mesh.edge_cell_b[edge_index])
        if 0 <= cell_a < counts.size and cell_b >= 0:
            counts[cell_a] += 1
        if 0 <= cell_b < counts.size:
            counts[cell_b] += 1
    return counts


def _cell_id(mesh: BoussinesqMesh, index: int) -> int:
    values = getattr(mesh, "cell_ids", None)
    if values is None:
        return int(index)
    return int(np.asarray(values).reshape(-1)[index])


def _cell_coord(mesh: BoussinesqMesh, index: int, names: tuple[str, ...]) -> float | None:
    for name in names:
        values = getattr(mesh, name, None)
        if values is None:
            continue
        array = np.asarray(values, dtype=float).reshape(-1)
        if index < array.size and np.isfinite(array[index]):
            return float(array[index])
    return None


def _quantiles(values: np.ndarray) -> dict[str, float]:
    array = np.asarray(values, dtype=float).reshape(-1)
    if array.size == 0:
        return {key: math.nan for key in ("min", "p01", "p05", "p50", "p95", "p99", "max")}
    return {
        "min": float(np.min(array)),
        "p01": float(np.quantile(array, 0.01)),
        "p05": float(np.quantile(array, 0.05)),
        "p50": float(np.quantile(array, 0.50)),
        "p95": float(np.quantile(array, 0.95)),
        "p99": float(np.quantile(array, 0.99)),
        "max": float(np.max(array)),
    }


def _jsonable(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return {str(key): _jsonable(item) for key, item in getattr(value, "__dict__", {}).items()}
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, np.ndarray):
        return [_jsonable(item) for item in value.tolist()]
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return value


__all__ = [
    "PICARD_LSCHEME_FINAL_CELLS_CSV",
    "PICARD_LSCHEME_ITERATIONS_CSV",
    "PICARD_LSCHEME_SUMMARY_JSON",
    "PICARD_VI_CYCLES_CSV",
    "PICARD_VI_CYCLE_SUMMARY_JSON",
    "PicardLschemeOptions",
    "PicardViCycleOptions",
    "bounded_picard_lscheme",
    "bounded_picard_vi_cycles",
    "write_picard_lscheme_diagnostics",
    "write_picard_vi_cycle_diagnostics",
]
