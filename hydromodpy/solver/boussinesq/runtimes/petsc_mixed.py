"""PETSc runtime for the Boussinesq backend on Linux.

This backend switches from the historical head-only regularized overflow law to
one semi-explicit mixed double-obstacle formulation:

- ``h`` remains the differential unknown,
- ``q_ex`` is one algebraic unknown per cell for saturation excess,
- ``q_dry`` is one algebraic unknown per cell for the lower obstacle.

Time integration still uses one backward-Euler step per stress period, but each
step now solves the coupled nonlinear DAE residual with PETSc SNES.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

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
    _fischer_burmeister_residual_and_gap_derivatives,
    _fischer_burmeister_residual_and_derivatives,
    _initial_steady_q_ex_guess,
    _initial_transient_q_ex_guess,
    _prescribed_head_vector,
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
    """Run one PETSc SNES solve on the mixed ``(h, q_ex, q_dry)`` formulation."""
    PETSc = _require_petsc()
    petsc_index_dtype = np.dtype(PETSc.IntType)
    n_cells = int(mesh.n_cells)
    n_unknowns = 3 * n_cells
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
    head_initial = _clip_free_head_to_obstacles(
        mesh,
        head_initial,
        prescribed_mask=prescribed_mask,
    )
    head_initial = _activate_lower_obstacle_in_initial_guess(
        mesh,
        head_initial,
        q_ex_initial,
        assembly_for=assembly_for,
        prescribed_mask=prescribed_mask,
    )
    q_dry_initial = _initial_q_dry_guess(
        mesh,
        head_m=head_initial,
        assembly=assembly_for(head_initial, q_ex_initial),
        prescribed_mask=prescribed_mask,
    )
    state0 = _stack_double_obstacle_state(head_initial, q_ex_initial, q_dry_initial)
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

    current_assembly = _assembly_with_dry_deficit(
        mesh,
        assembly_for(head_initial, q_ex_initial),
        q_dry_initial,
        prescribed_mask=prescribed_mask,
    )

    def _residual(_snes, state_vec, residual_vec) -> None:
        nonlocal current_assembly
        state = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        head_m, q_ex_rate_m_s, q_dry_rate_m_s = _split_double_obstacle_state(
            state,
            n_cells=n_cells,
        )
        current_assembly = _assembly_with_dry_deficit(
            mesh,
            assembly_for(head_m, q_ex_rate_m_s),
            q_dry_rate_m_s,
            prescribed_mask=prescribed_mask,
        )
        surface_gap_m = np.asarray(mesh.z_top_m, dtype=float) - head_m
        bottom_gap_m = head_m - np.asarray(mesh.z_bottom_m, dtype=float)
        surface_residual, _, _ = _fischer_burmeister_residual_and_derivatives(
            q_ex_rate_m_s,
            surface_gap_m,
            head_scale_m=float(head_scale_m),
            rate_scale_m_s=float(rate_scale_m_s),
        )
        bottom_residual, _, _ = _fischer_burmeister_residual_and_gap_derivatives(
            q_dry_rate_m_s,
            bottom_gap_m,
            head_scale_m=float(head_scale_m),
            rate_scale_m_s=float(rate_scale_m_s),
        )
        residual = np.asarray(residual_vec.getArray(), dtype=float)
        residual[:n_cells] = np.asarray(current_assembly.residual_m3_s, dtype=float)
        residual[n_cells : 2 * n_cells] = surface_residual
        residual[2 * n_cells :] = bottom_residual
        residual[n_cells : 2 * n_cells][prescribed_mask] = q_ex_rate_m_s[prescribed_mask]
        residual[2 * n_cells :][prescribed_mask] = q_dry_rate_m_s[prescribed_mask]

    def _jacobian(_snes, state_vec, jac, preconditioner) -> None:
        state = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        head_m, q_ex_rate_m_s, q_dry_rate_m_s = _split_double_obstacle_state(
            state,
            n_cells=n_cells,
        )
        surface_gap_m = np.asarray(mesh.z_top_m, dtype=float) - head_m
        bottom_gap_m = head_m - np.asarray(mesh.z_bottom_m, dtype=float)
        _, dphi_surface_dh, dphi_surface_dq = _fischer_burmeister_residual_and_derivatives(
            q_ex_rate_m_s,
            surface_gap_m,
            head_scale_m=float(head_scale_m),
            rate_scale_m_s=float(rate_scale_m_s),
        )
        _, dphi_bottom_dh, dphi_bottom_dq = (
            _fischer_burmeister_residual_and_gap_derivatives(
                q_dry_rate_m_s,
                bottom_gap_m,
                head_scale_m=float(head_scale_m),
                rate_scale_m_s=float(rate_scale_m_s),
            )
        )

        base_data, base_rows, base_cols = build_sparse_semianalytic_base_jacobian_triplets(
            mesh,
            head_m,
            dt_seconds=dt_seconds,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=drainage_conductance_m2_s,
        )
        free_rows = np.flatnonzero(~prescribed_mask).astype(int, copy=False)
        area = np.asarray(mesh.cell_area_m2, dtype=float)
        balance_q_ex_rows = free_rows
        balance_q_ex_cols = free_rows + n_cells
        balance_q_ex_data = area[free_rows]
        balance_q_dry_rows = free_rows
        balance_q_dry_cols = free_rows + 2 * n_cells
        balance_q_dry_data = -area[free_rows]
        surface_h_rows = free_rows + n_cells
        surface_h_cols = free_rows
        surface_h_data = np.asarray(dphi_surface_dh, dtype=float)[free_rows]
        surface_q_rows = np.arange(n_cells, dtype=int) + n_cells
        surface_q_cols = np.arange(n_cells, dtype=int) + n_cells
        surface_q_data = np.asarray(dphi_surface_dq, dtype=float)
        dry_h_rows = free_rows + 2 * n_cells
        dry_h_cols = free_rows
        dry_h_data = np.asarray(dphi_bottom_dh, dtype=float)[free_rows]
        dry_q_rows = np.arange(n_cells, dtype=int) + 2 * n_cells
        dry_q_cols = np.arange(n_cells, dtype=int) + 2 * n_cells
        dry_q_data = np.asarray(dphi_bottom_dq, dtype=float)
        if np.any(prescribed_mask):
            surface_q_data = surface_q_data.copy()
            surface_q_data[prescribed_mask] = 1.0
            dry_q_data = dry_q_data.copy()
            dry_q_data[prescribed_mask] = 1.0

        data = np.concatenate(
            (
                np.asarray(base_data, dtype=float).reshape(-1),
                balance_q_ex_data.reshape(-1),
                balance_q_dry_data.reshape(-1),
                surface_h_data.reshape(-1),
                surface_q_data.reshape(-1),
                dry_h_data.reshape(-1),
                dry_q_data.reshape(-1),
            )
        )
        row_indices = np.concatenate(
            (
                np.asarray(base_rows, dtype=int).reshape(-1),
                balance_q_ex_rows,
                balance_q_dry_rows,
                surface_h_rows,
                surface_q_rows,
                dry_h_rows,
                dry_q_rows,
            )
        )
        col_indices = np.concatenate(
            (
                np.asarray(base_cols, dtype=int).reshape(-1),
                balance_q_ex_cols,
                balance_q_dry_cols,
                surface_h_cols,
                surface_q_cols,
                dry_h_cols,
                dry_q_cols,
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
    head_m, q_ex_rate_m_s, q_dry_rate_m_s = _split_double_obstacle_state(
        state,
        n_cells=n_cells,
    )
    if np.any(prescribed_mask):
        head_m, q_ex_rate_m_s = _apply_prescribed_head_constraints(
            head_m,
            q_ex_rate_m_s,
            prescribed_head=prescribed_head,
            prescribed_mask=prescribed_mask,
        )
        q_dry_rate_m_s = np.asarray(q_dry_rate_m_s, dtype=float).copy()
        q_dry_rate_m_s[prescribed_mask] = 0.0
    current_assembly = _assembly_with_dry_deficit(
        mesh,
        assembly_for(head_m, q_ex_rate_m_s),
        q_dry_rate_m_s,
        prescribed_mask=prescribed_mask,
    )
    surface_gap_m = np.asarray(mesh.z_top_m, dtype=float) - head_m
    bottom_gap_m = head_m - np.asarray(mesh.z_bottom_m, dtype=float)
    surface_residual, _, _ = _fischer_burmeister_residual_and_derivatives(
        q_ex_rate_m_s,
        surface_gap_m,
        head_scale_m=float(head_scale_m),
        rate_scale_m_s=float(rate_scale_m_s),
    )
    bottom_residual, _, _ = _fischer_burmeister_residual_and_gap_derivatives(
        q_dry_rate_m_s,
        bottom_gap_m,
        head_scale_m=float(head_scale_m),
        rate_scale_m_s=float(rate_scale_m_s),
    )
    if np.any(prescribed_mask):
        surface_residual = np.asarray(surface_residual, dtype=float)
        bottom_residual = np.asarray(bottom_residual, dtype=float)
        surface_residual[prescribed_mask] = 0.0
        bottom_residual[prescribed_mask] = 0.0
    full_residual = np.concatenate(
        (
            np.asarray(current_assembly.residual_m3_s, dtype=float),
            np.asarray(surface_residual, dtype=float),
            np.asarray(bottom_residual, dtype=float),
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


def _clip_free_head_to_obstacles(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    prescribed_mask: np.ndarray,
) -> np.ndarray:
    """Return an initial head guess inside the double obstacle on free cells."""
    head = np.asarray(head_m, dtype=float).reshape(-1).copy()
    free = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    lower = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1)
    upper = np.maximum(np.asarray(mesh.z_top_m, dtype=float).reshape(-1), lower)
    head[free] = np.clip(head[free], lower[free], upper[free])
    return head


def _initial_q_dry_guess(
    mesh: BoussinesqMesh,
    *,
    head_m: np.ndarray,
    assembly: BoussinesqAssembly,
    prescribed_mask: np.ndarray,
) -> np.ndarray:
    """Return a warm-start estimate for the lower-obstacle correction rate."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    dry_active_guess = head <= np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1) + 1.0e-9
    area = np.asarray(mesh.cell_area_m2, dtype=float).reshape(-1)
    deficit_rate = np.divide(
        np.asarray(assembly.residual_m3_s, dtype=float).reshape(-1),
        area,
        out=np.zeros(mesh.n_cells, dtype=float),
        where=area > 0.0,
    )
    q_dry = np.where(dry_active_guess, np.maximum(deficit_rate, 0.0), 0.0)
    q_dry[np.asarray(prescribed_mask, dtype=bool).reshape(-1)] = 0.0
    return q_dry.astype(float, copy=False)


def _activate_lower_obstacle_in_initial_guess(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    q_ex_rate_m_s: np.ndarray,
    *,
    assembly_for: Callable[[np.ndarray, np.ndarray], BoussinesqAssembly],
    prescribed_mask: np.ndarray,
) -> np.ndarray:
    """Start on the lower obstacle where the free balance cannot dewater further."""
    head = np.asarray(head_m, dtype=float).reshape(-1).copy()
    free = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    if not np.any(free):
        return head
    bottom_trial = head.copy()
    bottom_trial[free] = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1)[free]
    bottom_residual = np.asarray(
        assembly_for(bottom_trial, q_ex_rate_m_s).residual_m3_s,
        dtype=float,
    ).reshape(-1)
    active_lower = free & (bottom_residual > 0.0)
    head[active_lower] = bottom_trial[active_lower]
    return head


def _assembly_with_dry_deficit(
    mesh: BoussinesqMesh,
    assembly: BoussinesqAssembly,
    q_dry_rate_m_s: np.ndarray,
    *,
    prescribed_mask: np.ndarray,
) -> BoussinesqAssembly:
    """Add the lower-obstacle correction to the balance residual only."""
    q_dry = np.asarray(q_dry_rate_m_s, dtype=float).reshape(-1).copy()
    q_dry[np.asarray(prescribed_mask, dtype=bool).reshape(-1)] = 0.0
    residual = np.asarray(assembly.residual_m3_s, dtype=float).reshape(-1).copy()
    residual -= np.asarray(mesh.cell_area_m2, dtype=float).reshape(-1) * q_dry
    return replace(assembly, residual_m3_s=residual, dry_deficit_rate_m_s=q_dry)


def _stack_double_obstacle_state(
    head_m: np.ndarray,
    q_ex_rate_m_s: np.ndarray,
    q_dry_rate_m_s: np.ndarray,
) -> np.ndarray:
    """Pack the mixed unknown ``(h, q_ex, q_dry)`` into one vector."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    q_ex = np.asarray(q_ex_rate_m_s, dtype=float).reshape(-1)
    q_dry = np.asarray(q_dry_rate_m_s, dtype=float).reshape(-1)
    if head.size != q_ex.size or head.size != q_dry.size:
        raise ValueError("head, q_ex and q_dry vectors must have the same size.")
    return np.concatenate((head, q_ex, q_dry)).astype(float, copy=False)


def _split_double_obstacle_state(
    state: np.ndarray,
    *,
    n_cells: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Unpack one contiguous mixed vector into ``(h, q_ex, q_dry)``."""
    vector = np.asarray(state, dtype=float).reshape(-1)
    expected_size = 3 * int(n_cells)
    if vector.size != expected_size:
        raise ValueError(
            f"Mixed PETSc state must have length {expected_size}; got {int(vector.size)}."
        )
    return (
        vector[:n_cells].astype(float, copy=False),
        vector[n_cells : 2 * n_cells].astype(float, copy=False),
        vector[2 * n_cells :].astype(float, copy=False),
    )


__all__ = [
    "_assembly_with_dry_deficit",
    "_activate_lower_obstacle_in_initial_guess",
    "_clip_free_head_to_obstacles",
    "_coo_to_csr",
    "_fischer_burmeister_residual_and_derivatives",
    "_initial_q_dry_guess",
    "_initial_transient_q_ex_guess",
    "_split_double_obstacle_state",
    "_stack_double_obstacle_state",
    "solve_steady_problem",
    "solve_transient_step",
]
