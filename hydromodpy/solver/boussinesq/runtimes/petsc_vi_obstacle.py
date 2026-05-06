"""Experimental PETSc SNESVI runtime for a head-only obstacle formulation.

This backend is intentionally separate from ``petsc_mixed``. It does not put
``q_ex`` or ``q_dry`` in the PETSc state vector and it does not use
Fischer-Burmeister residuals. PETSc solves only for ``h`` with explicit bounds
``z_bottom <= h <= z_top``; after convergence the remaining groundwater balance
residual on active bounds is reconstructed as a surface or bottom reaction.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    BoussinesqAssembly,
    assemble_steady_residual_with_saturation_excess,
    assemble_transient_residual_with_saturation_excess,
)
from hydromodpy.solver.boussinesq.jacobian.semianalytic import (
    build_sparse_semianalytic_base_jacobian_triplets,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)
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


def solve_transient_step(inputs: TransientStepInputs) -> RuntimeSolveResult:
    """Solve one transient implicit step as a PETSc bounded VI in head only."""
    if float(inputs.dt_seconds) <= 0.0:
        raise ValueError("dt_seconds must be strictly positive.")

    head_start = np.asarray(inputs.head_prev_m, dtype=float).copy()
    head_initial = (
        head_start.copy()
        if inputs.head_initial_guess_m is None
        else np.asarray(inputs.head_initial_guess_m, dtype=float).copy()
    )
    zero_surface_rate = np.zeros(int(inputs.mesh.n_cells), dtype=float)
    prescribed_head_m_by_cell = _prescribed_head_cells(inputs.prescribed_head_m_by_cell)
    requested_substeps = _normalize_substep_count(
        inputs.options.vi_substeps_per_period,
        label="vi_substeps_per_period",
    )
    attempt_counts = _substep_attempt_counts(
        requested_substeps=requested_substeps,
        adaptive_enabled=bool(inputs.options.vi_substep_on_failure),
        max_adaptive_substeps=int(inputs.options.vi_max_adaptive_substeps),
    )
    failed_attempts: list[dict[str, Any]] = []
    last_failure: RuntimeSolveResult | None = None

    for attempt_index, n_substeps in enumerate(attempt_counts):
        head_current = head_start.copy()
        substep_records: list[dict[str, Any]] = []
        substep_results: list[RuntimeSolveResult] = []
        dt_sub_seconds = float(inputs.dt_seconds) / float(n_substeps)

        # The period forcing is assumed to be a rate over the stress period.
        # Substepping changes dt in the implicit storage term but does not
        # rescale rate-based forcing values.
        for substep_index in range(int(n_substeps)):
            substep_initial = (
                head_initial
                if attempt_index == 0 and substep_index == 0
                else head_current
            )
            substep = _solve_transient_vi_substep(
                inputs=inputs,
                head_prev_m=head_current,
                head_initial_guess_m=substep_initial,
                dt_seconds=dt_sub_seconds,
                zero_surface_rate_m_s=zero_surface_rate,
                prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            )
            substep_results.append(substep)
            substep_records.append(
                _substep_diagnostic_record(
                    result=substep,
                    attempt_index=attempt_index,
                    substep_index=substep_index,
                    n_substeps_attempted=int(n_substeps),
                    dt_sub_seconds=dt_sub_seconds,
                )
            )
            if not substep.converged:
                last_failure = substep
                break
            head_current = np.asarray(substep.head_m, dtype=float).copy()

        attempt_summary = _attempt_diagnostic_record(
            attempt_index=attempt_index,
            n_substeps=int(n_substeps),
            substep_records=substep_records,
        )
        if substep_results and all(result.converged for result in substep_results):
            final_result = substep_results[-1]
            diagnostics = _period_substep_diagnostics(
                final_result=final_result,
                requested_substeps=requested_substeps,
                used_substeps=int(n_substeps),
                attempt_counts=attempt_counts,
                attempt_summaries=failed_attempts + [attempt_summary],
                substep_records=substep_records,
                adaptive_used=int(n_substeps) != requested_substeps,
                success=True,
            )
            termination_reason = str(final_result.termination_reason)
            if int(n_substeps) != requested_substeps:
                termination_reason = (
                    f"{termination_reason}; adaptive_vi_substeps_used={int(n_substeps)}"
                )
            return replace(
                final_result,
                iterations=_sum_substep_iterations(substep_records),
                termination_reason=termination_reason,
                diagnostics=diagnostics,
            )

        failed_attempts.append(attempt_summary)

    if last_failure is None:
        raise RuntimeError("PETSc VI substepping did not execute any substep.")
    restored = _restored_transient_failure_result(
        inputs=inputs,
        head_start_m=head_start,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        zero_surface_rate_m_s=zero_surface_rate,
        failed_result=last_failure,
    )
    diagnostics = _period_substep_diagnostics(
        final_result=last_failure,
        requested_substeps=requested_substeps,
        used_substeps=0,
        attempt_counts=attempt_counts,
        attempt_summaries=failed_attempts,
        substep_records=failed_attempts[-1].get("substeps", []) if failed_attempts else [],
        adaptive_used=len(attempt_counts) > 1,
        success=False,
    )
    return replace(
        restored,
        iterations=_sum_attempt_iterations(failed_attempts),
        diagnostics=diagnostics,
        termination_reason=(
            f"{last_failure.termination_reason}; failed_vi_substep_attempts="
            f"{list(int(value) for value in attempt_counts)}"
        ),
    )


def solve_steady_problem(inputs: SteadySolveInputs) -> RuntimeSolveResult:
    """Solve one steady balance as a PETSc bounded VI in head only."""
    zero_surface_rate = np.zeros(int(inputs.mesh.n_cells), dtype=float)
    prescribed_head_m_by_cell = _prescribed_head_cells(inputs.prescribed_head_m_by_cell)

    def _assembly_for(head_m: np.ndarray) -> BoussinesqAssembly:
        return assemble_steady_residual_with_saturation_excess(
            inputs.mesh,
            head_m=head_m,
            saturation_excess_rate_m_s=zero_surface_rate,
            recharge_rate_m_s=inputs.recharge_rate_m_s,
            well_flux_m3_s=inputs.well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
            regularization_radius=float(inputs.options.regularization_radius),
        )

    return _solve_vi_obstacle_problem(
        assembly_for=_assembly_for,
        head_initial_guess_m=np.asarray(inputs.head_initial_guess_m, dtype=float),
        mesh=inputs.mesh,
        dt_seconds=None,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(inputs.options.max_iterations),
        tol_residual_inf=float(inputs.options.tol_residual_inf),
        tol_state_update_inf=float(inputs.options.tol_state_update_inf),
        backend_name="petsc",
    )


def _solve_transient_vi_substep(
    *,
    inputs: TransientStepInputs,
    head_prev_m: np.ndarray,
    head_initial_guess_m: np.ndarray,
    dt_seconds: float,
    zero_surface_rate_m_s: np.ndarray,
    prescribed_head_m_by_cell: np.ndarray | None,
) -> RuntimeSolveResult:
    """Solve one Backward-Euler PETSc VI substep with period forcing held fixed."""
    head_prev = np.asarray(head_prev_m, dtype=float).copy()

    def _assembly_for(head_m: np.ndarray) -> BoussinesqAssembly:
        return assemble_transient_residual_with_saturation_excess(
            inputs.mesh,
            head_m=head_m,
            head_prev_m=head_prev,
            dt_seconds=float(dt_seconds),
            saturation_excess_rate_m_s=zero_surface_rate_m_s,
            recharge_rate_m_s=inputs.recharge_rate_m_s,
            well_flux_m3_s=inputs.well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
            regularization_radius=float(inputs.options.regularization_radius),
        )

    return _solve_vi_obstacle_problem(
        assembly_for=_assembly_for,
        head_initial_guess_m=np.asarray(head_initial_guess_m, dtype=float),
        mesh=inputs.mesh,
        dt_seconds=float(dt_seconds),
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(inputs.options.max_iterations),
        tol_residual_inf=float(inputs.options.tol_residual_inf),
        tol_state_update_inf=float(inputs.options.tol_state_update_inf),
        backend_name="petsc",
    )


def _restored_transient_failure_result(
    *,
    inputs: TransientStepInputs,
    head_start_m: np.ndarray,
    prescribed_head_m_by_cell: np.ndarray | None,
    zero_surface_rate_m_s: np.ndarray,
    failed_result: RuntimeSolveResult,
) -> RuntimeSolveResult:
    """Return a failed period result restored to the period-start head."""
    head_start = np.asarray(head_start_m, dtype=float).copy()
    raw_assembly = assemble_transient_residual_with_saturation_excess(
        inputs.mesh,
        head_m=head_start,
        head_prev_m=head_start,
        dt_seconds=float(inputs.dt_seconds),
        saturation_excess_rate_m_s=zero_surface_rate_m_s,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        regularization_radius=float(inputs.options.regularization_radius),
    )
    _, _, prescribed_mask = _variable_bounds(inputs.mesh, prescribed_head_m_by_cell)
    physical_lower = np.asarray(inputs.mesh.z_bottom_m, dtype=float).reshape(-1)
    physical_upper = np.maximum(
        np.asarray(inputs.mesh.z_top_m, dtype=float).reshape(-1),
        physical_lower,
    )
    assembly, _ = _reconstruct_obstacle_reactions(
        mesh=inputs.mesh,
        assembly=raw_assembly,
        head_m=head_start,
        physical_lower_m=physical_lower,
        physical_upper_m=physical_upper,
        prescribed_mask=prescribed_mask,
        tol_h=_obstacle_tolerance(float(inputs.options.tol_state_update_inf)),
    )
    return replace(failed_result, head_m=head_start, assembly=assembly)


def _normalize_substep_count(value: int, *, label: str) -> int:
    """Return a positive substep count."""
    count = int(value)
    if count <= 0:
        raise ValueError(f"{label} must be a positive integer; got {count}.")
    return count


def _substep_attempt_counts(
    *,
    requested_substeps: int,
    adaptive_enabled: bool,
    max_adaptive_substeps: int,
) -> tuple[int, ...]:
    """Return the fixed/adaptive substep counts to try for one period."""
    requested = _normalize_substep_count(
        requested_substeps,
        label="vi_substeps_per_period",
    )
    if not bool(adaptive_enabled):
        return (requested,)
    maximum = max(
        requested,
        _normalize_substep_count(
            max_adaptive_substeps,
            label="vi_max_adaptive_substeps",
        ),
    )
    attempts = [requested]
    while attempts[-1] < maximum:
        next_count = min(2 * attempts[-1], maximum)
        if next_count == attempts[-1]:
            break
        attempts.append(int(next_count))
    return tuple(attempts)


def _substep_diagnostic_record(
    *,
    result: RuntimeSolveResult,
    attempt_index: int,
    substep_index: int,
    n_substeps_attempted: int,
    dt_sub_seconds: float,
) -> dict[str, Any]:
    """Return one JSON-friendly diagnostic record for a substep solve."""
    diagnostics = dict(result.diagnostics or {})
    return {
        "attempt_index": int(attempt_index),
        "substep_index": int(substep_index),
        "n_substeps_attempted": int(n_substeps_attempted),
        "dt_sub_seconds": float(dt_sub_seconds),
        "success": bool(result.converged),
        "termination_reason": str(result.termination_reason),
        "snes_reason": int(diagnostics.get("snes_converged_reason", 0) or 0),
        "snes_reason_label": diagnostics.get("snes_converged_reason_label"),
        "ksp_reason": int(diagnostics.get("ksp_converged_reason", 0) or 0),
        "ksp_reason_label": diagnostics.get("ksp_converged_reason_label"),
        "snes_iterations": int(diagnostics.get("snes_iterations", result.iterations) or 0),
        "ksp_iterations": int(diagnostics.get("ksp_iterations", 0) or 0),
        "max_lower_violation_m": float(diagnostics.get("max_violation_lower_m", 0.0) or 0.0),
        "max_upper_violation_m": float(diagnostics.get("max_violation_upper_m", 0.0) or 0.0),
        "active_top_count": int(diagnostics.get("surface_active_cells", 0) or 0),
        "active_bottom_count": int(diagnostics.get("bottom_active_cells", 0) or 0),
        "free_count": int(diagnostics.get("free_cells", 0) or 0),
        "surface_reaction_total_m3_s": float(
            diagnostics.get("surface_reaction_total_m3_s", 0.0) or 0.0
        ),
        "bottom_reaction_total_m3_s": float(
            diagnostics.get("bottom_reaction_total_m3_s", 0.0) or 0.0
        ),
        "surface_reaction_total_m3": diagnostics.get("surface_reaction_total_m3"),
        "bottom_reaction_total_m3": diagnostics.get("bottom_reaction_total_m3"),
        "residual_norm_free": float(diagnostics.get("free_residual_norm_inf", 0.0) or 0.0),
        "residual_norm_projected": float(
            diagnostics.get("projected_vi_residual_norm_inf", result.residual_norm_inf) or 0.0
        ),
        "snes_type": diagnostics.get("snes_type"),
        "ksp_type": diagnostics.get("ksp_type"),
        "pc_type": diagnostics.get("pc_type"),
        "pc_factor_shift_type": diagnostics.get("pc_factor_shift_type"),
        "pc_factor_shift_amount": diagnostics.get("pc_factor_shift_amount"),
        "petsc_options": diagnostics.get("petsc_options"),
        "h_min_m": float(np.min(result.head_m)) if result.head_m.size else None,
        "h_max_m": float(np.max(result.head_m)) if result.head_m.size else None,
        "residual_min_m3_s": float(np.min(result.assembly.flow_residual_m3_s))
        if result.assembly.flow_residual_m3_s.size
        else None,
        "residual_max_m3_s": float(np.max(result.assembly.flow_residual_m3_s))
        if result.assembly.flow_residual_m3_s.size
        else None,
    }


def _attempt_diagnostic_record(
    *,
    attempt_index: int,
    n_substeps: int,
    substep_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return one compact diagnostic record for a fixed-substep attempt."""
    success = bool(substep_records) and all(bool(item["success"]) for item in substep_records)
    failed = [item for item in substep_records if not bool(item["success"])]
    return {
        "attempt_index": int(attempt_index),
        "n_substeps": int(n_substeps),
        "success": success,
        "completed_substeps": int(sum(1 for item in substep_records if bool(item["success"]))),
        "failed_substep_index": None if not failed else int(failed[0]["substep_index"]),
        "termination_reason": None if not failed else str(failed[0]["termination_reason"]),
        "snes_iterations": _sum_substep_iterations(substep_records),
        "ksp_iterations": _sum_substep_ksp_iterations(substep_records),
        "substeps": list(substep_records),
    }


def _period_substep_diagnostics(
    *,
    final_result: RuntimeSolveResult,
    requested_substeps: int,
    used_substeps: int,
    attempt_counts: tuple[int, ...],
    attempt_summaries: list[dict[str, Any]],
    substep_records: list[dict[str, Any]],
    adaptive_used: bool,
    success: bool,
) -> dict[str, Any]:
    """Return period-level diagnostics, preserving final SNESVI diagnostics."""
    diagnostics = dict(final_result.diagnostics or {})
    attempted_substeps = [
        int(item.get("n_substeps", used_substeps) or used_substeps)
        for item in attempt_summaries
    ]
    diagnostics.update(
        {
            "vi_substeps_requested": int(requested_substeps),
            "vi_substeps_used": int(used_substeps),
            "vi_substep_attempts": attempted_substeps or [int(value) for value in attempt_counts],
            "vi_substep_adaptive_used": bool(adaptive_used),
            "vi_substep_success": bool(success),
            "vi_substep_attempt_details": list(attempt_summaries),
            "vi_substep_details": list(substep_records),
            "vi_substep_total_snes_iterations": _sum_attempt_iterations(
                attempt_summaries[-1:] if success else attempt_summaries
            ),
            "vi_substep_total_ksp_iterations": _sum_attempt_ksp_iterations(
                attempt_summaries[-1:] if success else attempt_summaries
            ),
            "vi_substep_rate_forcing_rescaled": False,
            "vi_substep_surface_reaction_total_m3": _sum_optional_float(
                substep_records,
                "surface_reaction_total_m3",
            ),
            "vi_substep_bottom_reaction_total_m3": _sum_optional_float(
                substep_records,
                "bottom_reaction_total_m3",
            ),
        }
    )
    return diagnostics


def _sum_substep_iterations(records: list[dict[str, Any]]) -> int:
    """Return the total nonlinear iterations across substep records."""
    return int(sum(int(item.get("snes_iterations", 0) or 0) for item in records))


def _sum_substep_ksp_iterations(records: list[dict[str, Any]]) -> int:
    """Return the total linear iterations across substep records."""
    return int(sum(int(item.get("ksp_iterations", 0) or 0) for item in records))


def _sum_attempt_iterations(attempts: list[dict[str, Any]]) -> int:
    """Return the total nonlinear iterations across attempt records."""
    return int(sum(int(item.get("snes_iterations", 0) or 0) for item in attempts))


def _sum_attempt_ksp_iterations(attempts: list[dict[str, Any]]) -> int:
    """Return the total linear iterations across attempt records."""
    return int(sum(int(item.get("ksp_iterations", 0) or 0) for item in attempts))


def _sum_optional_float(records: list[dict[str, Any]], key: str) -> float:
    """Return the sum of nullable float values in substep records."""
    total = 0.0
    for item in records:
        value = item.get(key)
        if value is not None:
            total += float(value)
    return float(total)


def _solve_vi_obstacle_problem(
    *,
    assembly_for: Callable[[np.ndarray], BoussinesqAssembly],
    head_initial_guess_m: np.ndarray,
    mesh: BoussinesqMesh,
    dt_seconds: float | None,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    max_iterations: int,
    tol_residual_inf: float,
    tol_state_update_inf: float,
    backend_name: str,
) -> RuntimeSolveResult:
    """Run one PETSc SNESVI solve on the bounded head-only residual."""
    PETSc = _require_petsc()
    petsc_index_dtype = np.dtype(PETSc.IntType)
    n_cells = int(mesh.n_cells)
    lower_bound, upper_bound, prescribed_mask = _variable_bounds(
        mesh,
        prescribed_head_m_by_cell,
    )
    physical_lower = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1)
    physical_upper = np.maximum(np.asarray(mesh.z_top_m, dtype=float).reshape(-1), physical_lower)
    head0 = _clip_head_to_bounds(head_initial_guess_m, lower=lower_bound, upper=upper_bound)

    solution = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    residual_template = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    lower_vec = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    upper_vec = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    jacobian = PETSc.Mat().createAIJ(
        [n_cells, n_cells],
        nnz=12,
        comm=PETSc.COMM_SELF,
    )
    jacobian.setUp()
    jacobian.setOption(PETSc.Mat.Option.NEW_NONZERO_ALLOCATION_ERR, False)
    np.asarray(solution.getArray(), dtype=float)[:] = head0
    np.asarray(lower_vec.getArray(), dtype=float)[:] = lower_bound
    np.asarray(upper_vec.getArray(), dtype=float)[:] = upper_bound

    current_assembly = assembly_for(head0)

    def _residual(_snes, state_vec, residual_vec) -> None:
        nonlocal current_assembly
        head_m = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        current_assembly = assembly_for(head_m)
        residual = np.asarray(residual_vec.getArray(), dtype=float)
        residual[:] = np.asarray(current_assembly.solver_residual, dtype=float)

    def _jacobian(_snes, state_vec, jac, preconditioner) -> None:
        head_m = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        data, row_indices, col_indices = build_sparse_semianalytic_base_jacobian_triplets(
            mesh,
            head_m,
            dt_seconds=dt_seconds,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=drainage_conductance_m2_s,
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
    _configure_vi_snes(
        snes,
        tol_residual_inf=float(tol_residual_inf),
        max_iterations=int(max_iterations),
    )

    snes.solve(None, solution)
    head = np.asarray(solution.getArray(readonly=True), dtype=float).copy()
    raw_assembly = assembly_for(head)
    tol_h = _obstacle_tolerance(tol_state_update_inf)
    reacted_assembly, reaction_diagnostics = _reconstruct_obstacle_reactions(
        mesh=mesh,
        assembly=raw_assembly,
        head_m=head,
        physical_lower_m=physical_lower,
        physical_upper_m=physical_upper,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    projected_residual = _projected_vi_residual(
        residual=np.asarray(raw_assembly.solver_residual, dtype=float),
        head_m=head,
        lower_m=lower_bound,
        upper_m=upper_bound,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    residual_norm = residual_norm_inf(projected_residual)
    converged_reason = int(snes.getConvergedReason())
    reason_label = _snes_reason_label(converged_reason)
    termination_reason_base = (
        f"petsc SNESVI converged reason {converged_reason} ({reason_label})"
        if converged_reason > 0
        else f"petsc SNESVI failed reason {converged_reason} ({reason_label})"
    )
    converged, termination_reason = apply_residual_tolerance(
        success=converged_reason > 0,
        residual_norm_inf_value=residual_norm,
        tol_residual_inf=float(tol_residual_inf),
        termination_reason=termination_reason_base,
        residual_label="projected_vi_residual_inf",
    )
    diagnostics = _solver_diagnostics(
        snes,
        converged_reason=converged_reason,
        reason_label=reason_label,
        projected_vi_residual_norm_inf=residual_norm,
        free_residual_norm_inf_value=_free_residual_norm(
            residual=np.asarray(raw_assembly.flow_residual_m3_s, dtype=float),
            head_m=head,
            lower_m=physical_lower,
            upper_m=physical_upper,
            prescribed_mask=prescribed_mask,
            tol_h=tol_h,
        ),
        max_violation_lower_m=float(np.max(np.maximum(physical_lower - head, 0.0))),
        max_violation_upper_m=float(np.max(np.maximum(head - physical_upper, 0.0))),
        reaction_diagnostics=reaction_diagnostics,
        dt_seconds=dt_seconds,
    )
    return build_runtime_result(
        head_m=head,
        assembly=reacted_assembly,
        converged=bool(converged),
        iterations=int(snes.getIterationNumber()),
        residual_norm_inf_value=residual_norm,
        backend_name=str(backend_name),
        termination_reason=termination_reason,
        diagnostics=diagnostics,
    )


def _configure_vi_snes(
    snes,
    *,
    tol_residual_inf: float,
    max_iterations: int,
) -> None:
    """Apply experimental PETSc VI defaults while keeping options overrideable."""
    snes.setType("vinewtonrsls")
    snes.setTolerances(
        atol=float(tol_residual_inf),
        rtol=0.0,
        stol=0.0,
        max_it=int(max_iterations),
    )
    ksp = snes.getKSP()
    if ksp is not None:
        ksp.setType("preonly")
        ksp.setTolerances(rtol=1.0e-12, atol=0.0, max_it=1)
        pc = ksp.getPC()
        if pc is not None:
            pc.setType("lu")
            pc.setFromOptions()
        ksp.setFromOptions()
    snes.setFromOptions()


def _prescribed_head_cells(
    prescribed_head_m_by_cell: np.ndarray | None,
) -> np.ndarray | None:
    """Return the canonical prescribed-head cell vector, if provided."""
    if prescribed_head_m_by_cell is None:
        return None
    return np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)


def _variable_bounds(
    mesh: BoussinesqMesh,
    prescribed_head_m_by_cell: np.ndarray | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return PETSc VI lower/upper vectors and the prescribed-cell mask."""
    lower = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1).copy()
    upper = np.maximum(np.asarray(mesh.z_top_m, dtype=float).reshape(-1), lower)
    prescribed = (
        np.full(int(mesh.n_cells), np.nan, dtype=float)
        if prescribed_head_m_by_cell is None
        else np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)
    )
    if prescribed.size != int(mesh.n_cells):
        raise ValueError(
            "prescribed_head_m_by_cell must have length "
            f"{int(mesh.n_cells)}; got {int(prescribed.size)}."
        )
    prescribed_mask = np.isfinite(prescribed)
    if np.any(prescribed_mask):
        lower[prescribed_mask] = prescribed[prescribed_mask]
        upper[prescribed_mask] = prescribed[prescribed_mask]
    return lower, upper, prescribed_mask


def _clip_head_to_bounds(
    head_m: np.ndarray,
    *,
    lower: np.ndarray,
    upper: np.ndarray,
) -> np.ndarray:
    """Return one initial head guess inside the PETSc variable bounds."""
    head = np.asarray(head_m, dtype=float).reshape(-1).copy()
    if head.size != np.asarray(lower).size:
        raise ValueError(
            f"head_m length must match bounds ({int(head.size)} != {int(np.asarray(lower).size)})."
        )
    return np.clip(head, np.asarray(lower, dtype=float), np.asarray(upper, dtype=float))


def _obstacle_tolerance(tol_state_update_inf: float) -> float:
    """Return the tolerance used to classify active obstacle cells."""
    return max(1.0e-9, 10.0 * float(tol_state_update_inf))


def _reconstruct_obstacle_reactions(
    *,
    mesh: BoussinesqMesh,
    assembly: BoussinesqAssembly,
    head_m: np.ndarray,
    physical_lower_m: np.ndarray,
    physical_upper_m: np.ndarray,
    prescribed_mask: np.ndarray,
    tol_h: float,
) -> tuple[BoussinesqAssembly, dict[str, Any]]:
    """Reconstruct non-negative obstacle reactions from the raw balance residual."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    raw_residual = np.asarray(assembly.flow_residual_m3_s, dtype=float).reshape(-1)
    free_mask = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    surface_active = free_mask & (head >= np.asarray(physical_upper_m, dtype=float) - float(tol_h))
    bottom_active = free_mask & (head <= np.asarray(physical_lower_m, dtype=float) + float(tol_h))
    interior_free = free_mask & ~(surface_active | bottom_active)
    surface_reaction = np.where(surface_active, np.maximum(-raw_residual, 0.0), 0.0)
    bottom_reaction = np.where(bottom_active, np.maximum(raw_residual, 0.0), 0.0)
    area = np.asarray(mesh.cell_area_m2, dtype=float).reshape(-1)
    q_ex = np.divide(
        surface_reaction,
        area,
        out=np.zeros(int(mesh.n_cells), dtype=float),
        where=area > 0.0,
    )
    q_dry = np.divide(
        bottom_reaction,
        area,
        out=np.zeros(int(mesh.n_cells), dtype=float),
        where=area > 0.0,
    )
    correction = surface_reaction - bottom_reaction
    corrected_flow = raw_residual + correction
    corrected_residual = np.asarray(assembly.residual_m3_s, dtype=float).reshape(-1).copy()
    corrected_solver = np.asarray(assembly.solver_residual, dtype=float).reshape(-1).copy()
    corrected_residual[free_mask] = corrected_residual[free_mask] + correction[free_mask]
    corrected_solver[free_mask] = corrected_solver[free_mask] + correction[free_mask]
    diagnostics = {
        "surface_active_cells": int(np.count_nonzero(surface_active)),
        "bottom_active_cells": int(np.count_nonzero(bottom_active)),
        "free_cells": int(np.count_nonzero(interior_free)),
        "surface_reaction_total_m3_s": float(np.sum(surface_reaction)),
        "bottom_reaction_total_m3_s": float(np.sum(bottom_reaction)),
        "surface_reaction_wrong_sign_m3_s": float(
            np.max(np.where(surface_active, np.maximum(raw_residual, 0.0), 0.0))
        ),
        "bottom_reaction_wrong_sign_m3_s": float(
            np.max(np.where(bottom_active, np.maximum(-raw_residual, 0.0), 0.0))
        ),
    }
    reacted_assembly = replace(
        assembly,
        saturation_excess_rate_m_s=q_ex,
        dry_deficit_rate_m_s=q_dry,
        flow_residual_m3_s=corrected_flow,
        residual_m3_s=corrected_residual,
        solver_residual=corrected_solver,
    )
    return reacted_assembly, diagnostics


def _projected_vi_residual(
    *,
    residual: np.ndarray,
    head_m: np.ndarray,
    lower_m: np.ndarray,
    upper_m: np.ndarray,
    prescribed_mask: np.ndarray,
    tol_h: float,
) -> np.ndarray:
    """Return the residual left after applying bound complementarity signs.

    PETSc SNESVI accepts ``F >= 0`` on a lower active bound and ``F <= 0`` on
    an upper active bound. This helper mirrors that convention for the
    HydroModPy residual sign.
    """
    values = np.asarray(residual, dtype=float).reshape(-1)
    head = np.asarray(head_m, dtype=float).reshape(-1)
    lower = np.asarray(lower_m, dtype=float).reshape(-1)
    upper = np.asarray(upper_m, dtype=float).reshape(-1)
    projected = values.copy()
    prescribed = np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    free = ~prescribed
    lower_active = free & (head <= lower + float(tol_h))
    upper_active = free & (head >= upper - float(tol_h))
    interior = free & ~(lower_active | upper_active)
    projected[interior] = values[interior]
    projected[lower_active] = np.minimum(values[lower_active], 0.0)
    projected[upper_active] = np.maximum(values[upper_active], 0.0)
    return projected


def _free_residual_norm(
    *,
    residual: np.ndarray,
    head_m: np.ndarray,
    lower_m: np.ndarray,
    upper_m: np.ndarray,
    prescribed_mask: np.ndarray,
    tol_h: float,
) -> float:
    """Return the free-cell raw balance norm, excluding active obstacles."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    lower = np.asarray(lower_m, dtype=float).reshape(-1)
    upper = np.asarray(upper_m, dtype=float).reshape(-1)
    free = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    interior = free & (head > lower + float(tol_h)) & (head < upper - float(tol_h))
    if not np.any(interior):
        return 0.0
    return residual_norm_inf(np.asarray(residual, dtype=float).reshape(-1)[interior])


def _solver_diagnostics(
    snes,
    *,
    converged_reason: int,
    reason_label: str,
    projected_vi_residual_norm_inf: float,
    free_residual_norm_inf_value: float,
    max_violation_lower_m: float,
    max_violation_upper_m: float,
    reaction_diagnostics: dict[str, Any],
    dt_seconds: float | None,
) -> dict[str, Any]:
    """Return summary diagnostics exported by the Boussinesq drivers."""
    diagnostics: dict[str, Any] = {
        "snes_converged_reason": int(converged_reason),
        "snes_converged_reason_label": str(reason_label),
        "snes_iterations": int(snes.getIterationNumber()),
        "ksp_iterations": int(_linear_iteration_count(snes)),
        "ksp_converged_reason": int(_linear_converged_reason(snes)),
        "ksp_converged_reason_label": _ksp_reason_label(_linear_converged_reason(snes)),
        "max_violation_lower_m": float(max_violation_lower_m),
        "max_violation_upper_m": float(max_violation_upper_m),
        "free_residual_norm_inf": float(free_residual_norm_inf_value),
        "projected_vi_residual_norm_inf": float(projected_vi_residual_norm_inf),
    }
    diagnostics.update(_petsc_solver_configuration(snes))
    diagnostics.update(reaction_diagnostics)
    diagnostics["surface_reaction_total_m3"] = (
        None
        if dt_seconds is None
        else float(diagnostics["surface_reaction_total_m3_s"]) * float(dt_seconds)
    )
    diagnostics["bottom_reaction_total_m3"] = (
        None
        if dt_seconds is None
        else float(diagnostics["bottom_reaction_total_m3_s"]) * float(dt_seconds)
    )
    try:
        diagnostics["petsc_function_norm"] = float(snes.getFunctionNorm())
    except Exception:
        diagnostics["petsc_function_norm"] = None
    return diagnostics


def _petsc_solver_configuration(snes) -> dict[str, Any]:
    """Return PETSc SNES/KSP/PC option values when petsc4py exposes them."""
    values: dict[str, Any] = {"petsc_options": os.environ.get("PETSC_OPTIONS")}
    try:
        values["snes_type"] = snes.getType()
    except Exception:
        values["snes_type"] = None
    try:
        ksp = snes.getKSP()
    except Exception:
        ksp = None
    if ksp is None:
        values.update(
            {
                "ksp_type": None,
                "pc_type": None,
                "pc_factor_shift_type": None,
                "pc_factor_shift_amount": None,
            }
        )
        return values
    try:
        values["ksp_type"] = ksp.getType()
    except Exception:
        values["ksp_type"] = None
    try:
        pc = ksp.getPC()
    except Exception:
        pc = None
    if pc is None:
        values["pc_type"] = None
        values["pc_factor_shift_type"] = None
        values["pc_factor_shift_amount"] = None
        return values
    try:
        values["pc_type"] = pc.getType()
    except Exception:
        values["pc_type"] = None
    try:
        values["pc_factor_shift_type"] = str(pc.getFactorShiftType())
    except Exception:
        values["pc_factor_shift_type"] = None
    try:
        values["pc_factor_shift_amount"] = float(pc.getFactorShiftAmount())
    except Exception:
        values["pc_factor_shift_amount"] = None
    return values


def _linear_iteration_count(snes) -> int:
    """Return PETSc linear iterations when available."""
    try:
        return int(snes.getLinearSolveIterations())
    except Exception:
        pass
    try:
        ksp = snes.getKSP()
        if ksp is not None:
            return int(ksp.getIterationNumber())
    except Exception:
        pass
    return 0


def _linear_converged_reason(snes) -> int:
    """Return PETSc KSP converged reason when available."""
    try:
        ksp = snes.getKSP()
        if ksp is not None:
            return int(ksp.getConvergedReason())
    except Exception:
        pass
    return 0


def _ksp_reason_label(reason: int) -> str:
    """Return one readable label for common PETSc KSP reasons."""
    labels = {
        2: "KSP_CONVERGED_RTOL_NORMAL",
        3: "KSP_CONVERGED_ATOL_NORMAL",
        4: "KSP_CONVERGED_RTOL",
        5: "KSP_CONVERGED_ATOL",
        6: "KSP_CONVERGED_ITS",
        7: "KSP_CONVERGED_CG_NEG_CURVE",
        8: "KSP_CONVERGED_CG_CONSTRAINED",
        9: "KSP_CONVERGED_STEP_LENGTH",
        -2: "KSP_DIVERGED_NULL",
        -3: "KSP_DIVERGED_ITS",
        -4: "KSP_DIVERGED_DTOL",
        -5: "KSP_DIVERGED_BREAKDOWN",
        -6: "KSP_DIVERGED_BREAKDOWN_BICG",
        -7: "KSP_DIVERGED_NONSYMMETRIC",
        -8: "KSP_DIVERGED_INDEFINITE_PC",
        -9: "KSP_DIVERGED_NANORINF",
        -10: "KSP_DIVERGED_INDEFINITE_MAT",
        -11: "KSP_DIVERGED_PC_FAILED",
        0: "KSP_CONVERGED_ITERATING",
    }
    return labels.get(int(reason), f"KSP_REASON_{int(reason)}")


__all__ = [
    "_clip_head_to_bounds",
    "_projected_vi_residual",
    "_reconstruct_obstacle_reactions",
    "_variable_bounds",
    "solve_steady_problem",
    "solve_transient_step",
]
