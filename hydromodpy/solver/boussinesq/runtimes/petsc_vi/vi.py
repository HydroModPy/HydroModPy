"""VI orchestration: substeps, diagnostics records, top-level PETSc SNESVI solve."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    BoussinesqAssembly,
    assemble_transient_residual_with_saturation_excess,
)
from hydromodpy.solver.boussinesq.jacobian.semianalytic import (
    build_sparse_semianalytic_base_jacobian_triplets,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
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
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.obstacle import (
    clip_head_to_bounds,
    free_residual_norm,
    obstacle_tolerance,
    projected_vi_residual,
    reconstruct_obstacle_reactions,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.petsc import (
    accept_failed_snes_by_projected_tolerance,
    configure_vi_snes,
    ksp_reason_label,
    linear_converged_reason,
    linear_iteration_count,
    petsc_solver_configuration,
)
from hydromodpy.solver.boussinesq.runtimes.vi_bounds import (
    variable_bounds as _variable_bounds,
)


def solve_transient_vi_substep(
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

    return solve_vi_obstacle_problem(
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


def restored_transient_failure_result(
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
    _, upper_bound, prescribed_mask = _variable_bounds(
        inputs.mesh,
        prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
    )
    physical_lower = np.asarray(inputs.mesh.z_bottom_m, dtype=float).reshape(-1)
    physical_upper = upper_bound.copy()
    assembly, _ = reconstruct_obstacle_reactions(
        mesh=inputs.mesh,
        assembly=raw_assembly,
        head_m=head_start,
        physical_lower_m=physical_lower,
        physical_upper_m=physical_upper,
        prescribed_mask=prescribed_mask,
        tol_h=obstacle_tolerance(float(inputs.options.tol_state_update_inf)),
    )
    return replace(failed_result, head_m=head_start, assembly=assembly)


def normalize_substep_count(value: int, *, label: str) -> int:
    """Return a positive substep count."""
    count = int(value)
    if count <= 0:
        raise ValueError(f"{label} must be a positive integer; got {count}.")
    return count


def substep_attempt_counts(
    *,
    requested_substeps: int,
    adaptive_enabled: bool,
    max_adaptive_substeps: int,
) -> tuple[int, ...]:
    """Return the fixed/adaptive substep counts to try for one period."""
    requested = normalize_substep_count(
        requested_substeps,
        label="vi_substeps_per_period",
    )
    if not bool(adaptive_enabled):
        return (requested,)
    maximum = max(
        requested,
        normalize_substep_count(
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


def substep_diagnostic_record(
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


def attempt_diagnostic_record(
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
        "snes_iterations": sum_substep_iterations(substep_records),
        "ksp_iterations": sum_substep_ksp_iterations(substep_records),
        "substeps": list(substep_records),
    }


def period_substep_diagnostics(
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
        int(item.get("n_substeps", used_substeps) or used_substeps) for item in attempt_summaries
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
            "vi_substep_total_snes_iterations": sum_attempt_iterations(
                attempt_summaries[-1:] if success else attempt_summaries
            ),
            "vi_substep_total_ksp_iterations": sum_attempt_ksp_iterations(
                attempt_summaries[-1:] if success else attempt_summaries
            ),
            "vi_substep_rate_forcing_rescaled": False,
            "vi_substep_surface_reaction_total_m3": sum_optional_float(
                substep_records,
                "surface_reaction_total_m3",
            ),
            "vi_substep_bottom_reaction_total_m3": sum_optional_float(
                substep_records,
                "bottom_reaction_total_m3",
            ),
        }
    )
    return diagnostics


def sum_substep_iterations(records: list[dict[str, Any]]) -> int:
    """Return the total nonlinear iterations across substep records."""
    return int(sum(int(item.get("snes_iterations", 0) or 0) for item in records))


def sum_substep_ksp_iterations(records: list[dict[str, Any]]) -> int:
    """Return the total linear iterations across substep records."""
    return int(sum(int(item.get("ksp_iterations", 0) or 0) for item in records))


def sum_attempt_iterations(attempts: list[dict[str, Any]]) -> int:
    """Return the total nonlinear iterations across attempt records."""
    return int(sum(int(item.get("snes_iterations", 0) or 0) for item in attempts))


def sum_attempt_ksp_iterations(attempts: list[dict[str, Any]]) -> int:
    """Return the total linear iterations across attempt records."""
    return int(sum(int(item.get("ksp_iterations", 0) or 0) for item in attempts))


def sum_optional_float(records: list[dict[str, Any]], key: str) -> float:
    """Return the sum of nullable float values in substep records."""
    total = 0.0
    for item in records:
        value = item.get(key)
        if value is not None:
            total += float(value)
    return float(total)


def dry_equilibrium_result(
    *,
    mesh: BoussinesqMesh,
    assembly_for: Callable[[np.ndarray], BoussinesqAssembly],
    head_m: np.ndarray,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    tol_state_update_inf: float,
    backend_name: str,
    dry_diagnostics: dict[str, Any],
) -> RuntimeSolveResult:
    """Build a steady RuntimeSolveResult for a detected dry VI equilibrium."""
    lower_bound, upper_bound, prescribed_mask = _variable_bounds(
        mesh,
        prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    head = clip_head_to_bounds(
        np.asarray(head_m, dtype=float),
        lower=lower_bound,
        upper=upper_bound,
    )
    raw_assembly = assembly_for(head)
    tol_h = obstacle_tolerance(tol_state_update_inf)
    reacted_assembly, reaction_diagnostics = reconstruct_obstacle_reactions(
        mesh=mesh,
        assembly=raw_assembly,
        head_m=head,
        physical_lower_m=np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1),
        physical_upper_m=upper_bound,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    projected_residual = projected_vi_residual(
        residual=np.asarray(raw_assembly.solver_residual, dtype=float),
        head_m=head,
        lower_m=lower_bound,
        upper_m=upper_bound,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    residual_norm = residual_norm_inf(projected_residual)
    diagnostics: dict[str, Any] = {
        "snes_converged_reason": 0,
        "snes_converged_reason_label": "DRY_EQUILIBRIUM_DETECTED",
        "snes_iterations": 0,
        "ksp_iterations": 0,
        "ksp_converged_reason": 0,
        "ksp_converged_reason_label": "KSP_NOT_RUN_DRY_EQUILIBRIUM",
        "max_violation_lower_m": float(np.max(np.maximum(lower_bound - head, 0.0))),
        "max_violation_upper_m": float(np.max(np.maximum(head - upper_bound, 0.0))),
        "free_residual_norm_inf": free_residual_norm(
            residual=np.asarray(raw_assembly.flow_residual_m3_s, dtype=float),
            head_m=head,
            lower_m=np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1),
            upper_m=upper_bound,
            prescribed_mask=prescribed_mask,
            tol_h=tol_h,
        ),
        "projected_vi_residual_norm_inf": residual_norm,
        "accepted_by_projected_tolerance": True,
        "surface_reaction_total_m3": None,
        "bottom_reaction_total_m3": None,
    }
    diagnostics.update(reaction_diagnostics)
    diagnostics.update(dry_diagnostics)
    return build_runtime_result(
        head_m=head,
        assembly=reacted_assembly,
        converged=True,
        iterations=0,
        residual_norm_inf_value=residual_norm,
        backend_name=str(backend_name),
        termination_reason="dry equilibrium detected before PETSc SNESVI",
        diagnostics=diagnostics,
    )


def solver_diagnostics(
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
        "ksp_iterations": int(linear_iteration_count(snes)),
        "ksp_converged_reason": int(linear_converged_reason(snes)),
        "ksp_converged_reason_label": ksp_reason_label(linear_converged_reason(snes)),
        "max_violation_lower_m": float(max_violation_lower_m),
        "max_violation_upper_m": float(max_violation_upper_m),
        "free_residual_norm_inf": float(free_residual_norm_inf_value),
        "projected_vi_residual_norm_inf": float(projected_vi_residual_norm_inf),
    }
    diagnostics.update(petsc_solver_configuration(snes))
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


def solve_vi_obstacle_problem(  # noqa: PLR0915
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
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    physical_lower = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1)
    physical_upper = upper_bound.copy()
    head0 = clip_head_to_bounds(head_initial_guess_m, lower=lower_bound, upper=upper_bound)

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
    configure_vi_snes(
        PETSc,
        snes,
        tol_residual_inf=float(tol_residual_inf),
        max_iterations=int(max_iterations),
    )

    snes.solve(None, solution)
    head = np.asarray(solution.getArray(readonly=True), dtype=float).copy()
    raw_assembly = assembly_for(head)
    tol_h = obstacle_tolerance(tol_state_update_inf)
    reacted_assembly, reaction_diagnostics = reconstruct_obstacle_reactions(
        mesh=mesh,
        assembly=raw_assembly,
        head_m=head,
        physical_lower_m=physical_lower,
        physical_upper_m=physical_upper,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    projected_residual = projected_vi_residual(
        residual=np.asarray(raw_assembly.solver_residual, dtype=float),
        head_m=head,
        lower_m=lower_bound,
        upper_m=upper_bound,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    residual_norm = residual_norm_inf(projected_residual)
    max_violation_lower_m = float(np.max(np.maximum(physical_lower - head, 0.0)))
    max_violation_upper_m = float(np.max(np.maximum(head - physical_upper, 0.0)))
    converged_reason = int(snes.getConvergedReason())
    reason_label = _snes_reason_label(converged_reason)
    termination_reason_base = (
        f"petsc SNESVI converged reason {converged_reason} ({reason_label})"
        if converged_reason > 0
        else f"petsc SNESVI failed reason {converged_reason} ({reason_label})"
    )
    accepted_by_projected_tolerance = accept_failed_snes_by_projected_tolerance(
        converged_reason=converged_reason,
        residual_norm_inf_value=residual_norm,
        tol_residual_inf=tol_residual_inf,
        max_violation_lower_m=max_violation_lower_m,
        max_violation_upper_m=max_violation_upper_m,
        tol_h=tol_h,
    )
    if accepted_by_projected_tolerance:
        termination_reason_base = (
            f"{termination_reason_base}; accepted because projected_vi_residual_inf="
            f"{residual_norm:.3e} <= tol_residual_inf={float(tol_residual_inf):.3e} "
            "and VI bounds are satisfied"
        )
    converged, termination_reason = apply_residual_tolerance(
        success=converged_reason > 0 or accepted_by_projected_tolerance,
        residual_norm_inf_value=residual_norm,
        tol_residual_inf=float(tol_residual_inf),
        termination_reason=termination_reason_base,
        residual_label="projected_vi_residual_inf",
    )
    diagnostics = solver_diagnostics(
        snes,
        converged_reason=converged_reason,
        reason_label=reason_label,
        projected_vi_residual_norm_inf=residual_norm,
        free_residual_norm_inf_value=free_residual_norm(
            residual=np.asarray(raw_assembly.flow_residual_m3_s, dtype=float),
            head_m=head,
            lower_m=physical_lower,
            upper_m=physical_upper,
            prescribed_mask=prescribed_mask,
            tol_h=tol_h,
        ),
        max_violation_lower_m=max_violation_lower_m,
        max_violation_upper_m=max_violation_upper_m,
        reaction_diagnostics=reaction_diagnostics,
        dt_seconds=dt_seconds,
    )
    diagnostics["accepted_by_projected_tolerance"] = bool(accepted_by_projected_tolerance)
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
