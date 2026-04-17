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
    assemble_steady_residual,
    assemble_steady_residual_with_saturation_excess,
    assemble_transient_residual,
    assemble_transient_residual_with_saturation_excess,
)
from hydromodpy.solver.boussinesq.jacobian.semianalytic import (
    build_sparse_semianalytic_base_jacobian_triplets,
)
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh
from hydromodpy.solver.boussinesq.runtimes.petsc_common import (
    _configure_default_snes,
    _coo_to_csr,
    _require_petsc,
    _snes_reason_label,
)
from hydromodpy.solver.boussinesq.runtimes.execution_common import (
    apply_residual_tolerance,
    build_runtime_result,
    residual_norm_inf,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    SteadySolveInputs,
    TransientStepInputs,
)

_MIN_RATE_SCALE_M_S = 1.0e-12
_MIN_HEAD_SCALE_M = 1.0
_FB_JACOBIAN_EPS = 1.0e-12


def _complementarity_scales(
    mesh: BoussinesqMesh,
    *,
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
    dt_seconds: float | None,
) -> tuple[float, float]:
    """Return simple global scales used to nondimensionalize the NCP residual."""
    aquifer_thickness_m = np.maximum(mesh.z_top_m - mesh.z_bottom_m, 0.0)
    thickness_vector = np.asarray(aquifer_thickness_m, dtype=float).reshape(-1)
    head_scale_m = max(
        float(np.max(thickness_vector)) if thickness_vector.size else 0.0,
        _MIN_HEAD_SCALE_M,
    )

    recharge = np.asarray(
        recharge_rate_m_s if recharge_rate_m_s is not None else 0.0,
        dtype=float,
    ).reshape(-1)
    recharge_scale = float(np.max(np.abs(recharge))) if recharge.size else 0.0

    well_flux_raw = np.asarray(
        well_flux_m3_s if well_flux_m3_s is not None else 0.0,
        dtype=float,
    ).reshape(-1)
    if well_flux_raw.size == 0:
        well_rate = np.zeros(mesh.n_cells, dtype=float)
    elif well_flux_raw.size == 1:
        well_rate = np.full(
            mesh.n_cells,
            float(np.abs(well_flux_raw[0])),
            dtype=float,
        )
    elif well_flux_raw.size == mesh.n_cells:
        well_rate = np.abs(well_flux_raw).astype(float, copy=False)
    else:
        raise ValueError(
            "well_flux_m3_s must be scalar or cell-aligned for the PETSc backend."
        )
    well_rate = np.divide(
        well_rate,
        mesh.cell_area_m2,
        out=np.zeros(mesh.n_cells, dtype=float),
        where=mesh.cell_area_m2 > 0.0,
    )
    well_scale = float(np.max(well_rate)) if well_rate.size else 0.0

    conductivity = np.asarray(mesh.hydraulic_conductivity_m_s, dtype=float).reshape(-1)
    conductivity_scale = float(np.max(np.abs(conductivity))) if conductivity.size else 0.0
    storage_scale = 0.0
    if dt_seconds is not None and float(dt_seconds) > 0.0:
        storage = np.asarray(mesh.storage_coefficient, dtype=float).reshape(-1)
        storage_scale = float(
            np.max(np.abs(storage)) if storage.size else 0.0
        ) * head_scale_m / float(dt_seconds)

    rate_scale_m_s = max(
        recharge_scale,
        well_scale,
        conductivity_scale,
        storage_scale,
        _MIN_RATE_SCALE_M_S,
    )
    return head_scale_m, rate_scale_m_s


def _fischer_burmeister_residual_and_derivatives(
    q_ex_rate_m_s: np.ndarray,
    surface_gap_m: np.ndarray,
    *,
    head_scale_m: float,
    rate_scale_m_s: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return the NCP residual and its diagonal derivatives.

    The exact Fischer-Burmeister function is used in the residual so the
    complementarity condition still has the correct zero set. The derivative is
    regularized only through one tiny denominator floor to avoid singular
    divisions at ``(q_ex, gap) = (0, 0)``.
    """
    a = np.asarray(q_ex_rate_m_s, dtype=float) / float(rate_scale_m_s)
    b = np.asarray(surface_gap_m, dtype=float) / float(head_scale_m)
    radius = np.hypot(a, b)
    denominator = np.maximum(radius, _FB_JACOBIAN_EPS)
    residual = radius - a - b
    dphi_dq = (a / denominator - 1.0) / float(rate_scale_m_s)
    dphi_dh = (1.0 - b / denominator) / float(head_scale_m)
    return residual, dphi_dh, dphi_dq


def _stack_state(head_m: np.ndarray, q_ex_rate_m_s: np.ndarray) -> np.ndarray:
    """Pack the mixed unknown ``(h, q_ex)`` into one contiguous vector."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    q_ex = np.asarray(q_ex_rate_m_s, dtype=float).reshape(-1)
    if head.size != q_ex.size:
        raise ValueError("head and q_ex vectors must have the same size.")
    return np.concatenate((head, q_ex)).astype(float, copy=False)


def _split_state(state: np.ndarray, *, n_cells: int) -> tuple[np.ndarray, np.ndarray]:
    """Unpack one contiguous mixed vector into ``(h, q_ex)``."""
    vector = np.asarray(state, dtype=float).reshape(-1)
    if vector.size != 2 * int(n_cells):
        raise ValueError(
            f"Mixed PETSc state must have length {2 * int(n_cells)}; got {int(vector.size)}."
        )
    return (
        vector[:n_cells].astype(float, copy=False),
        vector[n_cells:].astype(float, copy=False),
    )


def _initial_transient_q_ex_guess(
    mesh: BoussinesqMesh,
    *,
    head_initial_guess_m: np.ndarray,
    head_prev_m: np.ndarray,
    dt_seconds: float,
    recharge_rate_m_s: np.ndarray | float | None,
    well_flux_m3_s: np.ndarray | float | None,
    prescribed_head_m_by_cell: np.ndarray | None = None,
    drainage_conductance_m2_s: np.ndarray | float | None = None,
    regularization_radius: float = 0.05,
) -> np.ndarray:
    """Return a robust transient warm start for the algebraic overflow rate.

    The mixed transient solve is especially sensitive during dry-down periods:
    one regularized-partition warm start can keep many cells spuriously active
    in ``q_ex`` even though the complementarity solution of the new period
    drives ``q_ex`` back to zero everywhere. When no explicit positive source
    acts on the system for the new period, we therefore start from the dry
    state. Under active recharge or injection, we keep the historical
    regularized-partition predictor so the solver still enters wetting/overflow
    phases with a physically informed seed.
    """
    recharge = np.asarray(
        recharge_rate_m_s if recharge_rate_m_s is not None else 0.0,
        dtype=float,
    ).reshape(-1)
    well_flux = np.asarray(
        well_flux_m3_s if well_flux_m3_s is not None else 0.0,
        dtype=float,
    ).reshape(-1)
    has_positive_surface_loading = bool(np.any(recharge > 0.0)) or bool(
        np.any(well_flux < 0.0)
    )
    if not has_positive_surface_loading:
        return np.zeros(mesh.n_cells, dtype=float)
    guess = np.maximum(
        np.asarray(
            assemble_transient_residual(
                mesh,
                head_m=head_initial_guess_m,
                head_prev_m=head_prev_m,
                dt_seconds=float(dt_seconds),
                recharge_rate_m_s=recharge_rate_m_s,
                well_flux_m3_s=well_flux_m3_s,
                prescribed_head_m_by_cell=prescribed_head_m_by_cell,
                drainage_conductance_m2_s=drainage_conductance_m2_s,
                regularization_radius=float(regularization_radius),
            ).saturation_excess_rate_m_s,
            dtype=float,
        ),
        0.0,
    )
    if prescribed_head_m_by_cell is not None:
        prescribed_mask = np.isfinite(
            np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)
        )
        guess[np.asarray(prescribed_mask, dtype=bool)] = 0.0
    return guess


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
    q_ex_initial = np.maximum(
        np.asarray(
            assemble_steady_residual(
                inputs.mesh,
                head_m=head_initial,
                recharge_rate_m_s=inputs.recharge_rate_m_s,
                well_flux_m3_s=inputs.well_flux_m3_s,
                prescribed_head_m_by_cell=inputs.prescribed_head_m_by_cell,
                drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
                regularization_radius=float(inputs.options.regularization_radius),
            ).saturation_excess_rate_m_s,
            dtype=float,
        ),
        0.0,
    )
    if inputs.prescribed_head_m_by_cell is not None:
        prescribed_mask = np.isfinite(
            np.asarray(inputs.prescribed_head_m_by_cell, dtype=float).reshape(-1)
        )
        q_ex_initial[np.asarray(prescribed_mask, dtype=bool)] = 0.0

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

    prescribed_head = np.asarray(
        prescribed_head_m_by_cell
        if prescribed_head_m_by_cell is not None
        else np.full(n_cells, np.nan, dtype=float),
        dtype=float,
    ).reshape(-1)
    prescribed_mask = np.isfinite(prescribed_head)
    head_initial = np.asarray(head_initial_guess_m, dtype=float).reshape(-1).copy()
    head_initial[prescribed_mask] = prescribed_head[prescribed_mask]
    q_ex_initial = np.asarray(q_ex_initial_rate_m_s, dtype=float).reshape(-1).copy()
    q_ex_initial[prescribed_mask] = 0.0
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
        residual[:n_cells] = np.asarray(current_assembly.residual_m3_s, dtype=float)
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
        head_m = np.asarray(head_m, dtype=float).copy()
        q_ex_rate_m_s = np.asarray(q_ex_rate_m_s, dtype=float).copy()
        head_m[prescribed_mask] = prescribed_head[prescribed_mask]
        q_ex_rate_m_s[prescribed_mask] = 0.0
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
            np.asarray(current_assembly.residual_m3_s, dtype=float),
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


__all__ = ["solve_steady_problem", "solve_transient_step"]

