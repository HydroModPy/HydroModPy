"""PETSc runtime for the regularized partition surface-interaction model.

This backend keeps the current head-only Boussinesq residual and solves it with
PETSc SNES. Surface interaction follows the regularized partition law

``q_ex = G_r(theta) R(balance)``

instead of the mixed complementarity ``(h, q_ex)`` formulation, and its
Jacobian is assembled analytically almost everywhere.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    BoussinesqAssembly,
)
from hydromodpy.solver.boussinesq.head_only_runtime_common import (
    build_steady_assembly_callback,
    build_transient_assembly_callback,
)
from hydromodpy.solver.boussinesq.jacobian_semianalytic import (
    build_sparse_semianalytic_regularized_partition_jacobian_triplets,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.partition_runtime_utils import (
    interiorize_regularized_partition_initial_guess,
    regularized_partition_jacobian_shift,
)
from hydromodpy.solver.boussinesq.petsc_common import (
    _configure_default_snes,
    _coo_to_csr,
    _require_petsc,
    _snes_reason_label,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)


def solve_transient_step(inputs: TransientStepInputs) -> RuntimeSolveResult:
    """Solve one transient implicit step with PETSc on the head-only system."""
    solve_setup = build_transient_assembly_callback(inputs)

    return _solve_nonlinear_system(
        assembly_for=solve_setup.assembly_for,
        head_initial_guess_m=solve_setup.head_initial_guess_m,
        mesh=inputs.mesh,
        dt_seconds=float(inputs.dt_seconds),
        surface_input_rate_m_s=inputs.recharge_rate_m_s,
        regularization_radius=float(solve_setup.options.regularization_radius),
        prescribed_head_m_by_cell=solve_setup.prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(solve_setup.options.max_iterations),
        tol_residual_inf=float(solve_setup.options.tol_residual_inf),
        backend_name="petsc",
    )


def solve_steady_problem(inputs: SteadySolveInputs) -> RuntimeSolveResult:
    """Solve one steady nonlinear balance with PETSc on the head-only system."""
    solve_setup = build_steady_assembly_callback(
        inputs,
        head_transform=lambda values: interiorize_regularized_partition_initial_guess(
            inputs.mesh,
            np.asarray(values, dtype=float),
        ),
    )

    return _solve_nonlinear_system(
        assembly_for=solve_setup.assembly_for,
        head_initial_guess_m=solve_setup.head_initial_guess_m,
        mesh=inputs.mesh,
        dt_seconds=None,
        surface_input_rate_m_s=inputs.recharge_rate_m_s,
        regularization_radius=float(solve_setup.options.regularization_radius),
        prescribed_head_m_by_cell=solve_setup.prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        max_iterations=int(solve_setup.options.max_iterations),
        tol_residual_inf=float(solve_setup.options.tol_residual_inf),
        backend_name="petsc",
    )


def _solve_nonlinear_system(
    *,
    assembly_for: Callable[[np.ndarray], BoussinesqAssembly],
    head_initial_guess_m: np.ndarray,
    mesh: BoussinesqMesh,
    dt_seconds: float | None,
    surface_input_rate_m_s: np.ndarray | float | None,
    regularization_radius: float,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
    max_iterations: int,
    tol_residual_inf: float,
    backend_name: str,
) -> RuntimeSolveResult:
    """Run one PETSc SNES solve on the head-only regularized partition system."""
    PETSc = _require_petsc()
    petsc_index_dtype = np.dtype(PETSc.IntType)
    n_cells = int(mesh.n_cells)

    head0 = np.asarray(head_initial_guess_m, dtype=float).reshape(-1)
    solution = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    residual_template = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    jacobian = PETSc.Mat().createAIJ(
        [n_cells, n_cells],
        nnz=12,
        comm=PETSc.COMM_SELF,
    )
    jacobian.setUp()
    jacobian.setOption(PETSc.Mat.Option.NEW_NONZERO_ALLOCATION_ERR, False)
    np.asarray(solution.getArray(), dtype=float)[:] = head0

    current_assembly = assembly_for(head0)
    initial_residual_norm_inf = float(
        np.linalg.norm(np.asarray(current_assembly.residual_m3_s, dtype=float), ord=np.inf)
    )

    def _residual(_snes, state_vec, residual_vec) -> None:
        nonlocal current_assembly
        head_m = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        current_assembly = assembly_for(head_m)
        residual = np.asarray(residual_vec.getArray(), dtype=float)
        residual[:] = np.asarray(current_assembly.residual_m3_s, dtype=float)

    def _jacobian(_snes, state_vec, jac, preconditioner) -> None:
        nonlocal current_assembly
        head_m = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        current_assembly = assembly_for(head_m)
        data, row_indices, col_indices = _build_sparse_jacobian_triplets(
            mesh=mesh,
            head_m=head_m,
            dt_seconds=dt_seconds,
            surface_input_rate_m_s=surface_input_rate_m_s,
            regularization_radius=regularization_radius,
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
            diagonal_shift = regularized_partition_jacobian_shift(
                _csr_diagonal(
                    indptr=indptr,
                    indices=indices,
                    values=values,
                    n_rows=n_cells,
                ),
                residual_norm_inf=float(
                    np.linalg.norm(
                        np.asarray(current_assembly.residual_m3_s, dtype=float),
                        ord=np.inf,
                    )
                ),
                initial_residual_norm_inf=initial_residual_norm_inf,
            )
            if diagonal_shift > 0.0:
                matrix.shift(float(diagonal_shift))

    snes = PETSc.SNES().create(comm=PETSc.COMM_SELF)
    snes.setFunction(_residual, residual_template)
    snes.setJacobian(_jacobian, jacobian, jacobian)
    _configure_default_snes(
        snes,
        tol_residual_inf=float(tol_residual_inf),
        max_iterations=int(max_iterations),
        prefer_direct_linear_solve=True,
    )

    snes.solve(None, solution)
    head = np.asarray(solution.getArray(readonly=True), dtype=float).copy()
    current_assembly = assembly_for(head)
    residual_norm_inf = float(
        np.linalg.norm(np.asarray(current_assembly.residual_m3_s, dtype=float), ord=np.inf)
    )
    converged_reason = int(snes.getConvergedReason())
    converged = converged_reason > 0 and residual_norm_inf <= float(tol_residual_inf)
    reason_label = _snes_reason_label(converged_reason)
    termination_reason = (
        f"petsc SNES converged reason {converged_reason} ({reason_label})"
        if converged_reason > 0
        else f"petsc SNES failed reason {converged_reason} ({reason_label})"
    )
    if residual_norm_inf > float(tol_residual_inf):
        termination_reason = (
            f"{termination_reason}; residual_inf={residual_norm_inf:.3e} "
            f"exceeds tol_residual_inf={float(tol_residual_inf):.3e}"
        )
    return RuntimeSolveResult(
        head_m=head,
        assembly=current_assembly,
        converged=bool(converged),
        iterations=int(snes.getIterationNumber()),
        residual_norm_inf=residual_norm_inf,
        backend_name=str(backend_name),
        termination_reason=termination_reason,
    )


def _build_sparse_jacobian_triplets(
    *,
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    dt_seconds: float | None,
    surface_input_rate_m_s: np.ndarray | float | None,
    regularization_radius: float,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build the sparse Jacobian used by the PETSc partition runtime."""
    return build_sparse_semianalytic_regularized_partition_jacobian_triplets(
        mesh,
        head_m,
        dt_seconds=dt_seconds,
        regularization_radius=regularization_radius,
        surface_input_rate_m_s=surface_input_rate_m_s,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )


def _csr_diagonal(
    *,
    indptr: np.ndarray,
    indices: np.ndarray,
    values: np.ndarray,
    n_rows: int,
) -> np.ndarray:
    """Extract the diagonal from one CSR triplet set."""
    diagonal = np.zeros(int(n_rows), dtype=float)
    indptr_array = np.asarray(indptr, dtype=int)
    indices_array = np.asarray(indices, dtype=int)
    values_array = np.asarray(values, dtype=float)
    for row_index in range(int(n_rows)):
        row_start = int(indptr_array[row_index])
        row_end = int(indptr_array[row_index + 1])
        row_mask = indices_array[row_start:row_end] == row_index
        if np.any(row_mask):
            diagonal[row_index] = float(np.sum(values_array[row_start:row_end][row_mask]))
    return diagonal


__all__ = ["solve_steady_problem", "solve_transient_step"]
