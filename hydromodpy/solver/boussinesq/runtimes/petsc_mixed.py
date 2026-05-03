"""PETSc runtime for the Boussinesq backend on Linux.

This backend switches from the historical head-only regularized overflow law to
one semi-explicit mixed formulation:

- ``h`` remains the differential unknown,
- ``q_ex`` becomes one algebraic unknown per cell,
- the surface constraint is enforced through a nonlinear complementarity
  relation ``0 <= q_ex âŸ‚ z_top - h >= 0``.

Time integration still uses one backward-Euler step per stress period, but each
step now solves the coupled nonlinear DAE residual with PETSc SNES.
"""

from __future__ import annotations

from collections.abc import Callable

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
    _configure_default_snes,
    _coo_to_csr,
    _require_petsc,
    _snes_reason_label,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_mixed_common import (
    _apply_prescribed_head_constraints,
    _complementarity_scales,
    _fischer_burmeister_residual_and_derivatives,
    _initial_steady_q_ex_guess,
    _initial_transient_q_ex_guess,
    _prescribed_head_vector,
    _split_state,
    _stack_state,
)


def solve_transient_step(inputs: TransientStepInputs) -> RuntimeSolveResult:
    """Solve one implicit transient DAE step with PETSc SNES."""
    if float(inputs.dt_seconds) <= 0.0:
        raise ValueError("dt_seconds must be strictly positive.")

    head_prev = np.asarray(inputs.head_prev_m, dtype=float)
    head_initial = (
        head_prev.copy()
        if inputs.head_initial_guess_m is None
        else np.asarray(inputs.head_initial_guess_m, dtype=float).copy()
    )
    q_ex_initial = _initial_transient_q_ex_guess(
        inputs.mesh,
        head_initial_guess_m=head_initial,
        head_prev_m=head_prev,
        dt_seconds=float(inputs.dt_seconds),
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=inputs.prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        regularization_radius=float(inputs.options.regularization_radius),
    )

    def _assembly_for(head_m: np.ndarray, q_ex_rate_m_s: np.ndarray) -> BoussinesqAssembly:
        return assemble_transient_residual_with_saturation_excess(
            inputs.mesh,
            head_m=head_m,
            head_prev_m=head_prev,
            dt_seconds=float(inputs.dt_seconds),
            saturation_excess_rate_m_s=q_ex_rate_m_s,
            recharge_rate_m_s=inputs.recharge_rate_m_s,
            well_flux_m3_s=inputs.well_flux_m3_s,
            prescribed_head_m_by_cell=inputs.prescribed_head_m_by_cell,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
            regularization_radius=float(inputs.options.regularization_radius),
        )

    return _solve_mixed_problem(
        mesh=inputs.mesh,
        head_initial_guess_m=head_initial,
        q_ex_initial_rate_m_s=q_ex_initial,
        assembly_for=_assembly_for,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        dt_seconds=float(inputs.dt_seconds),
        prescribed_head_m_by_cell=inputs.prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(inputs.options.max_iterations),
        tol_residual_inf=float(inputs.options.tol_residual_inf),
        backend_name="petsc",
    )


def solve_steady_problem(inputs: SteadySolveInputs) -> RuntimeSolveResult:
    """Solve one steady mixed complementarity system with PETSc SNES."""
    head_initial = np.asarray(inputs.head_initial_guess_m, dtype=float).copy()
    q_ex_initial = _initial_steady_q_ex_guess(
        inputs.mesh,
        head_initial_guess_m=head_initial,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=inputs.prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        regularization_radius=float(inputs.options.regularization_radius),
    )

    def _assembly_for(head_m: np.ndarray, q_ex_rate_m_s: np.ndarray) -> BoussinesqAssembly:
        return assemble_steady_residual_with_saturation_excess(
            inputs.mesh,
            head_m=head_m,
            saturation_excess_rate_m_s=q_ex_rate_m_s,
            recharge_rate_m_s=inputs.recharge_rate_m_s,
            well_flux_m3_s=inputs.well_flux_m3_s,
            prescribed_head_m_by_cell=inputs.prescribed_head_m_by_cell,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
            regularization_radius=float(inputs.options.regularization_radius),
        )

    return _solve_mixed_problem(
        mesh=inputs.mesh,
        head_initial_guess_m=head_initial,
        q_ex_initial_rate_m_s=q_ex_initial,
        assembly_for=_assembly_for,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        dt_seconds=None,
        prescribed_head_m_by_cell=inputs.prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(inputs.options.max_iterations),
        tol_residual_inf=float(inputs.options.tol_residual_inf),
        backend_name="petsc",
    )


def _solve_mixed_problem(
    *,
    mesh: BoussinesqMesh,
    head_initial_guess_m: np.ndarray,
    q_ex_initial_rate_m_s: np.ndarray,
    assembly_for: Callable[[np.ndarray, np.ndarray], BoussinesqAssembly],
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
    dt_seconds: float | None,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    max_iterations: int,
    tol_residual_inf: float,
    backend_name: str,
) -> RuntimeSolveResult:
    """Run one PETSc SNES solve on the mixed ``(h, q_ex)`` formulation."""
    PETSc = _require_petsc()
    petsc_index_dtype = np.dtype(PETSc.IntType)
    n_cells = int(mesh.n_cells)
    n_unknowns = 2 * n_cells
    head_scale_m, rate_scale_m_s = _complementarity_scales(
        mesh,
        recharge_rate_m_s=recharge_rate_m_s,
        well_flux_m3_s=well_flux_m3_s,
        dt_seconds=dt_seconds,
    )

    prescribed_head, prescribed_mask = _prescribed_head_vector(
        prescribed_head_m_by_cell,
        n_cells=n_cells,
    )
    head_initial, q_ex_initial = _apply_prescribed_head_constraints(
        head_initial_guess_m,
        q_ex_initial_rate_m_s,
        prescribed_head=prescribed_head,
        prescribed_mask=prescribed_mask,
    )
    state0 = _stack_state(head_initial, q_ex_initial)
    solution = PETSc.Vec().createSeq(n_unknowns, comm=PETSc.COMM_SELF)
    residual_template = PETSc.Vec().createSeq(n_unknowns, comm=PETSc.COMM_SELF)
    jacobian = PETSc.Mat().createAIJ(
        [n_unknowns, n_unknowns],
        nnz=16,
        comm=PETSc.COMM_SELF,
    )
    jacobian.setUp()
    jacobian.setOption(PETSc.Mat.Option.NEW_NONZERO_ALLOCATION_ERR, False)
    solution_array = np.asarray(solution.getArray(), dtype=float)
    solution_array[:] = np.asarray(state0, dtype=float)

    current_assembly = assembly_for(head_initial, q_ex_initial)

    def _residual(_snes, state_vec, residual_vec) -> None:
        nonlocal current_assembly
        state = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        head_m, q_ex_rate_m_s = _split_state(state, n_cells=n_cells)
        current_assembly = assembly_for(head_m, q_ex_rate_m_s)
        surface_gap_m = np.asarray(mesh.z_top_m, dtype=float) - head_m
        complementarity_residual, _, _ = _fischer_burmeister_residual_and_derivatives(
            q_ex_rate_m_s,
            surface_gap_m,
            head_scale_m=float(head_scale_m),
            rate_scale_m_s=float(rate_scale_m_s),
        )
        residual = np.asarray(residual_vec.getArray(), dtype=float)
        residual[:n_cells] = np.asarray(current_assembly.solver_residual, dtype=float)
        residual[n_cells:] = complementarity_residual
        residual[n_cells:][prescribed_mask] = q_ex_rate_m_s[prescribed_mask]

    def _jacobian(_snes, state_vec, jac, preconditioner) -> None:
        state = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        head_m, q_ex_rate_m_s = _split_state(state, n_cells=n_cells)
        surface_gap_m = np.asarray(mesh.z_top_m, dtype=float) - head_m
        _, dphi_dh, dphi_dq = _fischer_burmeister_residual_and_derivatives(
            q_ex_rate_m_s,
            surface_gap_m,
            head_scale_m=float(head_scale_m),
            rate_scale_m_s=float(rate_scale_m_s),
        )

        base_data, base_rows, base_cols = build_sparse_semianalytic_base_jacobian_triplets(
            mesh,
            head_m,
            dt_seconds=dt_seconds,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=drainage_conductance_m2_s,
        )
        free_rows = np.flatnonzero(~prescribed_mask).astype(int, copy=False)
        top_right_rows = free_rows
        top_right_cols = free_rows + n_cells
        top_right_data = np.asarray(mesh.cell_area_m2, dtype=float)[free_rows]
        bottom_left_rows = free_rows + n_cells
        bottom_left_cols = free_rows
        bottom_left_data = np.asarray(dphi_dh, dtype=float)[free_rows]
        bottom_right_rows = np.arange(n_cells, dtype=int) + n_cells
        bottom_right_cols = np.arange(n_cells, dtype=int) + n_cells
        bottom_right_data = np.asarray(dphi_dq, dtype=float)
        if np.any(prescribed_mask):
            bottom_right_data = bottom_right_data.copy()
            bottom_right_data[prescribed_mask] = 1.0

        data = np.concatenate(
            (
                np.asarray(base_data, dtype=float).reshape(-1),
                top_right_data.reshape(-1),
                bottom_left_data.reshape(-1),
                bottom_right_data.reshape(-1),
            )
        )
        row_indices = np.concatenate(
            (
                np.asarray(base_rows, dtype=int).reshape(-1),
                top_right_rows,
                bottom_left_rows,
                bottom_right_rows,
            )
        )
        col_indices = np.concatenate(
            (
                np.asarray(base_cols, dtype=int).reshape(-1),
                top_right_cols,
                bottom_left_cols,
                bottom_right_cols,
            )
        )
        indptr, indices, values = _coo_to_csr(
            n_rows=n_unknowns,
            n_cols=n_unknowns,
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
    _configure_default_snes(
        snes,
        tol_residual_inf=float(tol_residual_inf),
        max_iterations=int(max_iterations),
    )

    snes.solve(None, solution)
    state = np.asarray(solution.getArray(readonly=True), dtype=float).copy()
    head_m, q_ex_rate_m_s = _split_state(state, n_cells=n_cells)
    if np.any(prescribed_mask):
        head_m, q_ex_rate_m_s = _apply_prescribed_head_constraints(
            head_m,
            q_ex_rate_m_s,
            prescribed_head=prescribed_head,
            prescribed_mask=prescribed_mask,
        )
    current_assembly = assembly_for(head_m, q_ex_rate_m_s)
    surface_gap_m = np.asarray(mesh.z_top_m, dtype=float) - head_m
    complementarity_residual, _, _ = _fischer_burmeister_residual_and_derivatives(
        q_ex_rate_m_s,
        surface_gap_m,
        head_scale_m=float(head_scale_m),
        rate_scale_m_s=float(rate_scale_m_s),
    )
    if np.any(prescribed_mask):
        complementarity_residual = np.asarray(complementarity_residual, dtype=float)
        complementarity_residual[prescribed_mask] = 0.0
    full_residual = np.concatenate(
        (
            np.asarray(current_assembly.solver_residual, dtype=float),
            np.asarray(complementarity_residual, dtype=float),
        )
    )
    residual_norm = residual_norm_inf(full_residual)
    converged_reason = int(snes.getConvergedReason())
    reason_label = _snes_reason_label(converged_reason)
    termination_reason_base = (
        f"petsc SNES converged reason {converged_reason} ({reason_label})"
        if converged_reason > 0
        else f"petsc SNES failed reason {converged_reason} ({reason_label})"
    )
    converged, termination_reason = apply_residual_tolerance(
        success=converged_reason > 0,
        residual_norm_inf_value=residual_norm,
        tol_residual_inf=float(tol_residual_inf),
        termination_reason=termination_reason_base,
        residual_label="full_residual_inf",
    )
    return build_runtime_result(
        head_m=head_m,
        assembly=current_assembly,
        converged=bool(converged),
        iterations=int(snes.getIterationNumber()),
        residual_norm_inf_value=residual_norm,
        backend_name=str(backend_name),
        termination_reason=termination_reason,
    )


__all__ = [
    "_coo_to_csr",
    "_fischer_burmeister_residual_and_derivatives",
    "_initial_transient_q_ex_guess",
    "solve_steady_problem",
    "solve_transient_step",
]
