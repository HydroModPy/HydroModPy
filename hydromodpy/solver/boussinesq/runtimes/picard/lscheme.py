"""Picard/L-scheme iterate: bounded relaxed linear system + projection."""

from __future__ import annotations

import math
import time
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.solver.boussinesq.assembly.fluxes import (
    harmonic_conductivity,
    saturated_thickness_from_head,
)
from hydromodpy.solver.boussinesq.assembly.inputs import as_cell_vector
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
)
from hydromodpy.solver.boussinesq.runtimes.picard.diagnostics import (
    DRY_THICKNESS_TOL_M,
    MIN_DISTANCE_M,
    PicardIterationRecord,
    PicardLschemeOptions,
    clip_head,
    free_mask_from_bounds,
    jsonable,
    physical_bounds,
    prescribed_head_cells,
    quantiles,
)
from hydromodpy.solver.boussinesq.runtimes.picard.picard import (
    assemble_strict_steady_residual,
    runtime_result_from_raw_assembly,
    solve_strict_vi_obstacle,
    strict_drainage_conductance,
)


def lagged_internal_tau(
    mesh: BoussinesqMesh,
    *,
    thickness: np.ndarray,
    edge_index: int,
) -> float:
    """Return one lagged internal-edge transmissibility coefficient."""
    cell_a = int(mesh.edge_cell_a[edge_index])
    cell_b = int(mesh.edge_cell_b[edge_index])
    if cell_b < 0:
        return 0.0
    conductivity_edge = harmonic_conductivity(
        float(mesh.hydraulic_conductivity_m_s[cell_a]),
        float(mesh.hydraulic_conductivity_m_s[cell_b]),
    )
    thickness_edge = 0.5 * (float(thickness[cell_a]) + float(thickness[cell_b]))
    distance = max(float(mesh.edge_distance_m[edge_index]), MIN_DISTANCE_M)
    return (
        max(conductivity_edge, 0.0)
        * max(thickness_edge, 0.0)
        * float(mesh.edge_length_m[edge_index])
        / distance
    )


def resolve_lscheme_L(
    mesh: BoussinesqMesh,
    *,
    base_diag: np.ndarray,
    lscheme_L: float | str,
) -> float:
    """Resolve the L-scheme diagonal stabilization."""
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


def picard_linear_system(  # noqa: PLR0915
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
        tau = lagged_internal_tau(mesh, thickness=thickness, edge_index=edge_index)
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

    conductance = strict_drainage_conductance(
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

    Lstab = resolve_lscheme_L(mesh, base_diag=base_diag, lscheme_L=lscheme_L)
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


def solve_sparse_system(matrix, rhs: np.ndarray) -> np.ndarray:
    """Solve a sparse linear system; raise on warnings to detect singular solves."""
    try:
        from scipy.sparse.linalg import spsolve
    except Exception as exc:  # pragma: no cover - depends on optional dependency state
        raise RuntimeError("stationary_picard_lscheme requires scipy.sparse.linalg.") from exc
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        return np.asarray(spsolve(matrix, np.asarray(rhs, dtype=float)), dtype=float).reshape(-1)


def accept_relaxed_candidate(
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
    """Halve omega until the candidate residual fits the growth factor."""
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
        candidate = clip_head(
            candidate,
            lower=lower,
            upper=upper,
            project_bounds=bool(options.picard_project_bounds),
        )
        raw = assemble_strict_steady_residual(
            mesh,
            candidate,
            recharge_rate_m_s=inputs.recharge_rate_m_s,
            well_flux_m3_s=inputs.well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        )
        candidate_result = runtime_result_from_raw_assembly(
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


def iteration_record(
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
    """Build one PicardIterationRecord from a Picard iterate result."""
    head = np.asarray(result.head_m, dtype=float)
    tol_h = max(1.0e-9, 10.0 * 1.0e-12)
    free_mask = free_mask_from_bounds(head=head, lower=lower, upper=upper, tol_h=tol_h)
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
        physically_dry_count=int(np.count_nonzero(thickness <= DRY_THICKNESS_TOL_M)),
        max_lower_violation=float(np.max(np.maximum(lower - head, 0.0))),
        max_upper_violation=float(np.max(np.maximum(head - upper, 0.0))),
        linear_solve_status=str(linear_solve_status),
        note=str(note),
    )


def picard_summary(
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
    """Return a JSON-friendly summary of one Picard/L-scheme run."""
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
        "cells_physically_dry_count": int(np.count_nonzero(thickness <= DRY_THICKNESS_TOL_M)),
        "max_lower_violation": float(np.max(np.maximum(lower - head, 0.0))),
        "max_upper_violation": float(np.max(np.maximum(head - upper, 0.0))),
        "h_min": float(np.min(head)) if head.size else math.nan,
        "h_max": float(np.max(head)) if head.size else math.nan,
        "physical_saturated_thickness_quantiles": quantiles(thickness),
        "transmissivity_quantiles": quantiles(transmissivity),
        "runtime_seconds": float(runtime_seconds),
        "picard_options": jsonable(options.__dict__),
    }
    if final_vi_result is not None:
        summary["final_vi_iterations"] = int(final_vi_result.iterations)
        summary["final_vi_termination_reason"] = str(final_vi_result.termination_reason)
    return summary


def bounded_picard_lscheme(  # noqa: PLR0915
    inputs: SteadySolveInputs,
    *,
    picard_options: PicardLschemeOptions | None = None,
    diagnostics_dir: str | Path | None = None,
    case_id: str = "",
) -> RuntimeSolveResult:
    """Run the experimental strict bounded Picard/L-scheme initializer."""
    from hydromodpy.solver.boussinesq.runtimes.picard.io import (
        write_picard_lscheme_diagnostics,
    )

    options = picard_options or PicardLschemeOptions()
    start = time.perf_counter()
    mesh = inputs.mesh
    prescribed = prescribed_head_cells(inputs.prescribed_head_m_by_cell, n_cells=mesh.n_cells)
    lower, upper, prescribed_mask = physical_bounds(mesh, prescribed)
    head = clip_head(
        np.asarray(inputs.head_initial_guess_m, dtype=float).reshape(-1),
        lower=lower,
        upper=upper,
        project_bounds=bool(options.picard_project_bounds),
    )

    raw_assembly = assemble_strict_steady_residual(
        mesh,
        head,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
    )
    result = runtime_result_from_raw_assembly(
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
                matrix, rhs, Lstab = picard_linear_system(
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
                trial = solve_sparse_system(matrix, rhs)
                linear_solve_status = "ok"
            except Exception as exc:  # noqa: BLE001 - diagnostic path
                stop_reason = "linear_solve_failed"
                linear_solve_status = f"{type(exc).__name__}: {exc}"
                break

            if not np.all(np.isfinite(trial)):
                stop_reason = "linear_solve_failed"
                linear_solve_status = "nonfinite_solution"
                break

            accepted, omega_used, note = accept_relaxed_candidate(
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
                iteration_record(
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
            final_vi_result = solve_strict_vi_obstacle(
                inputs,
                head_initial_guess_m=result.head_m,
            )
        except Exception as exc:  # noqa: BLE001 - diagnostic path
            final_vi_error = repr(exc)

    summary = picard_summary(
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
        merged["picard_head_before_final_vi_m"] = jsonable(result.head_m)
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
