"""Experimental PETSc TS + SNESVI runtime for a head-only obstacle problem.

The PETSc state vector contains only hydraulic head ``h``. PETSc SNESVI bounds
that state with ``z_bottom <= h <= z_top`` and PETSc TS performs fixed
Backward-Euler steps inside the HydroModPy stress period. Surface and bottom
rates are reconstructed after convergence from the remaining implicit residual;
``q_ex`` and ``q_dry`` are not primary unknowns and no Fischer-Burmeister
equations are assembled here.
"""

from __future__ import annotations

import os
from dataclasses import replace
from typing import Any

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    BoussinesqAssembly,
    assemble_steady_residual_with_saturation_excess,
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

_DEFAULT_PC_FACTOR_SHIFT_TYPE = "nonzero"
_DEFAULT_PC_FACTOR_SHIFT_AMOUNT = 1.0e-10


def solve_transient_step(inputs: TransientStepInputs) -> RuntimeSolveResult:
    """Solve one stress period using PETSc TS Backward Euler and SNESVI."""
    if float(inputs.dt_seconds) <= 0.0:
        raise ValueError("dt_seconds must be strictly positive.")
    if bool(inputs.options.ts_vi_adapt):
        raise NotImplementedError(
            "petsc_ts_vi_obstacle currently supports fixed PETSc TS steps only; "
            "TSAdapt is not exposed by the petsc4py TS API available in this environment."
        )

    PETSc = _require_petsc()
    n_cells = int(inputs.mesh.n_cells)
    petsc_index_dtype = np.dtype(PETSc.IntType)
    ts_steps = _normalize_step_count(inputs.options.ts_vi_steps_per_period)
    dt_period = float(inputs.dt_seconds)
    dt_initial = dt_period / float(ts_steps)
    prescribed = _prescribed_head_cells(inputs.prescribed_head_m_by_cell)
    lower, upper, prescribed_mask = _variable_bounds(inputs.mesh, prescribed)
    physical_lower = np.asarray(inputs.mesh.z_bottom_m, dtype=float).reshape(-1)
    physical_upper = np.maximum(
        np.asarray(inputs.mesh.z_top_m, dtype=float).reshape(-1),
        physical_lower,
    )
    head_start = _clip_head_to_bounds(
        np.asarray(inputs.head_prev_m, dtype=float),
        lower=lower,
        upper=upper,
    )
    zero_surface_rate = np.zeros(n_cells, dtype=float)
    tol_h = _obstacle_tolerance(float(inputs.options.tol_state_update_inf))

    solution = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    residual_template = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    lower_vec = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    upper_vec = PETSc.Vec().createSeq(n_cells, comm=PETSc.COMM_SELF)
    jacobian = PETSc.Mat().createAIJ([n_cells, n_cells], nnz=12, comm=PETSc.COMM_SELF)
    jacobian.setUp()
    jacobian.setOption(PETSc.Mat.Option.NEW_NONZERO_ALLOCATION_ERR, False)
    np.asarray(solution.getArray(), dtype=float)[:] = head_start
    np.asarray(lower_vec.getArray(), dtype=float)[:] = lower
    np.asarray(upper_vec.getArray(), dtype=float)[:] = upper

    def _assembly_for(head_m: np.ndarray, hdot_m_s: np.ndarray) -> BoussinesqAssembly:
        return _assemble_implicit_residual(
            inputs=inputs,
            head_m=head_m,
            hdot_m_s=hdot_m_s,
            zero_surface_rate_m_s=zero_surface_rate,
            prescribed_head_m_by_cell=prescribed,
            prescribed_mask=prescribed_mask,
        )

    def _ifunction(_ts, _time, state_vec, derivative_vec, residual_vec) -> None:
        head = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        hdot = np.asarray(derivative_vec.getArray(readonly=True), dtype=float)
        assembly = _assembly_for(head, hdot)
        residual = np.asarray(residual_vec.getArray(), dtype=float)
        residual[:] = np.asarray(assembly.solver_residual, dtype=float)

    def _ijacobian(_ts, _time, state_vec, _derivative_vec, shift, jac, preconditioner) -> None:
        head = np.asarray(state_vec.getArray(readonly=True), dtype=float)
        dt_for_storage = 1.0 / float(shift) if float(shift) > 0.0 else None
        data, row_indices, col_indices = build_sparse_semianalytic_base_jacobian_triplets(
            inputs.mesh,
            head,
            dt_seconds=dt_for_storage,
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

    step_records: list[dict[str, Any]] = []
    previous_head = head_start.copy()
    previous_time = 0.0
    last_raw_assembly: BoussinesqAssembly | None = None
    last_reacted_assembly: BoussinesqAssembly | None = None
    last_reaction_diagnostics: dict[str, Any] = {}

    def _monitor(ts, step_number: int, time_value: float, state_vec) -> None:
        nonlocal previous_head, previous_time, last_raw_assembly
        nonlocal last_reacted_assembly, last_reaction_diagnostics
        if int(step_number) <= 0:
            previous_head = np.asarray(state_vec.getArray(readonly=True), dtype=float).copy()
            previous_time = float(time_value)
            return
        head = np.asarray(state_vec.getArray(readonly=True), dtype=float).copy()
        dt_step = max(float(time_value) - previous_time, 0.0)
        hdot = np.zeros_like(head) if dt_step <= 0.0 else (head - previous_head) / dt_step
        raw_assembly = _assembly_for(head, hdot)
        reacted_assembly, reaction_diagnostics = _reaction_state(
            mesh=inputs.mesh,
            assembly=raw_assembly,
            head_m=head,
            lower_bound_m=lower,
            upper_bound_m=upper,
            physical_lower_m=physical_lower,
            physical_upper_m=physical_upper,
            prescribed_mask=prescribed_mask,
            tol_h=tol_h,
        )
        last_raw_assembly = raw_assembly
        last_reacted_assembly = reacted_assembly
        last_reaction_diagnostics = reaction_diagnostics
        step_records.append(
            _step_diagnostic_record(
                ts=ts,
                step_index=int(step_number) - 1,
                time_seconds=float(time_value),
                dt_seconds=dt_step,
                raw_assembly=raw_assembly,
                head_m=head,
                reaction_diagnostics=reaction_diagnostics,
                physical_lower_m=physical_lower,
                physical_upper_m=physical_upper,
            )
        )
        previous_head = head
        previous_time = float(time_value)

    ts = PETSc.TS().create(comm=PETSc.COMM_SELF)
    ts.setType(str(inputs.options.ts_vi_type or "beuler"))
    ts.setProblemType(PETSc.TS.ProblemType.NONLINEAR)
    ts.setTime(0.0)
    ts.setMaxTime(dt_period)
    ts.setTimeStep(dt_initial)
    ts.setMaxSteps(ts_steps if not bool(inputs.options.ts_vi_adapt) else ts_steps * 16)
    ts.setExactFinalTime(PETSc.TS.ExactFinalTime.MATCHSTEP)
    ts.setIFunction(_ifunction, residual_template)
    ts.setIJacobian(_ijacobian, jacobian, jacobian)
    ts.setMonitor(_monitor)

    snes = ts.getSNES()
    snes.setVariableBounds(lower_vec, upper_vec)
    _configure_ts_vi_snes(
        PETSc,
        snes,
        snes_type=str(inputs.options.ts_vi_snes_type or "vinewtonrsls"),
        tol_residual_inf=float(inputs.options.tol_residual_inf),
        max_iterations=int(inputs.options.max_iterations),
    )
    ts.setFromOptions()

    exception: Exception | None = None
    try:
        ts.solve(solution)
    except Exception as exc:  # pragma: no cover - depends on PETSc failure mode
        exception = exc

    head = np.asarray(solution.getArray(readonly=True), dtype=float).copy()
    if last_reacted_assembly is None or last_raw_assembly is None:
        hdot = (head - head_start) / dt_period
        last_raw_assembly = _assembly_for(head, hdot)
        last_reacted_assembly, last_reaction_diagnostics = _reaction_state(
            mesh=inputs.mesh,
            assembly=last_raw_assembly,
            head_m=head,
            lower_bound_m=lower,
            upper_bound_m=upper,
            physical_lower_m=physical_lower,
            physical_upper_m=physical_upper,
            prescribed_mask=prescribed_mask,
            tol_h=tol_h,
        )

    residual_norm = float(last_reaction_diagnostics.get("projected_vi_residual_norm_inf", 0.0))
    ts_reason = int(ts.getConvergedReason()) if exception is None else -99
    ts_reason_label = _ts_reason_label(ts_reason)
    snes_reason = int(snes.getConvergedReason())
    snes_reason_label = _snes_reason_label(snes_reason)
    termination_reason_base = (
        f"petsc TSVI converged reason {ts_reason} ({ts_reason_label})"
        if ts_reason > 0 and exception is None
        else f"petsc TSVI failed reason {ts_reason} ({ts_reason_label})"
    )
    if exception is not None:
        termination_reason_base = f"{termination_reason_base}; {type(exception).__name__}: {exception}"
    converged, termination_reason = apply_residual_tolerance(
        success=ts_reason > 0 and exception is None,
        residual_norm_inf_value=residual_norm,
        tol_residual_inf=float(inputs.options.tol_residual_inf),
        termination_reason=termination_reason_base,
        residual_label="projected_vi_residual_inf",
    )
    total_snes_iterations = int(
        sum(int(row.get("snes_iterations", 0) or 0) for row in step_records)
    )
    diagnostics = _period_diagnostics(
        ts=ts,
        snes=snes,
        ts_reason=ts_reason,
        ts_reason_label=ts_reason_label,
        snes_reason=snes_reason,
        snes_reason_label=snes_reason_label,
        ts_steps_requested=ts_steps,
        dt_period_seconds=dt_period,
        dt_initial_seconds=dt_initial,
        step_records=step_records,
        reaction_diagnostics=last_reaction_diagnostics,
        residual_norm=residual_norm,
        head_m=head,
        physical_lower_m=physical_lower,
        physical_upper_m=physical_upper,
        ts_vi_adapt=bool(inputs.options.ts_vi_adapt),
        dt_min_seconds=(
            dt_period * float(inputs.options.ts_vi_dt_min_fraction)
            if bool(inputs.options.ts_vi_adapt)
            else dt_initial
        ),
        dt_max_seconds=(
            dt_period * float(inputs.options.ts_vi_dt_max_fraction)
            if bool(inputs.options.ts_vi_adapt)
            else dt_initial
        ),
    )
    return build_runtime_result(
        head_m=head,
        assembly=last_reacted_assembly,
        converged=bool(converged),
        iterations=total_snes_iterations,
        residual_norm_inf_value=residual_norm,
        backend_name="petsc",
        termination_reason=termination_reason,
        diagnostics=diagnostics,
    )


def solve_steady_problem(inputs: SteadySolveInputs) -> RuntimeSolveResult:
    """The first TS VI prototype is transient-only."""
    raise NotImplementedError("petsc_ts_vi_obstacle currently supports transient runs only.")


def _assemble_implicit_residual(
    *,
    inputs: TransientStepInputs,
    head_m: np.ndarray,
    hdot_m_s: np.ndarray,
    zero_surface_rate_m_s: np.ndarray,
    prescribed_head_m_by_cell: np.ndarray | None,
    prescribed_mask: np.ndarray,
) -> BoussinesqAssembly:
    """Assemble ``F(t, h, hdot)`` while keeping stress-period forcing as rates."""
    steady = assemble_steady_residual_with_saturation_excess(
        inputs.mesh,
        head_m=head_m,
        saturation_excess_rate_m_s=zero_surface_rate_m_s,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        regularization_radius=float(inputs.options.regularization_radius),
    )
    storage = (
        np.asarray(inputs.mesh.cell_area_m2, dtype=float).reshape(-1)
        * np.asarray(inputs.mesh.storage_coefficient, dtype=float).reshape(-1)
        * np.asarray(hdot_m_s, dtype=float).reshape(-1)
    )
    flow_residual = np.asarray(steady.flow_residual_m3_s, dtype=float).copy() + storage
    solver_residual = np.asarray(steady.solver_residual, dtype=float).copy()
    free = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    solver_residual[free] = flow_residual[free]
    prescribed_flux = np.asarray(steady.prescribed_head_flux_m3_s, dtype=float).copy()
    if np.any(prescribed_mask):
        prescribed_flux[prescribed_mask] = -flow_residual[prescribed_mask]
    return replace(
        steady,
        prescribed_head_flux_m3_s=prescribed_flux,
        flow_residual_m3_s=flow_residual,
        solver_residual=solver_residual,
        residual_m3_s=flow_residual.copy(),
    )


def _reaction_state(
    *,
    mesh: BoussinesqMesh,
    assembly: BoussinesqAssembly,
    head_m: np.ndarray,
    lower_bound_m: np.ndarray,
    upper_bound_m: np.ndarray,
    physical_lower_m: np.ndarray,
    physical_upper_m: np.ndarray,
    prescribed_mask: np.ndarray,
    tol_h: float,
) -> tuple[BoussinesqAssembly, dict[str, Any]]:
    reacted, diagnostics = _reconstruct_obstacle_reactions(
        mesh=mesh,
        assembly=assembly,
        head_m=head_m,
        physical_lower_m=physical_lower_m,
        physical_upper_m=physical_upper_m,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    projected = _projected_vi_residual(
        residual=np.asarray(assembly.solver_residual, dtype=float),
        head_m=head_m,
        lower_m=lower_bound_m,
        upper_m=upper_bound_m,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    diagnostics["projected_vi_residual_norm_inf"] = residual_norm_inf(projected)
    diagnostics["free_residual_norm_inf"] = _free_residual_norm(
        residual=np.asarray(assembly.flow_residual_m3_s, dtype=float),
        head_m=head_m,
        lower_m=physical_lower_m,
        upper_m=physical_upper_m,
        prescribed_mask=prescribed_mask,
        tol_h=tol_h,
    )
    return reacted, diagnostics


def _configure_ts_vi_snes(PETSc, snes, *, snes_type: str, tol_residual_inf: float, max_iterations: int) -> None:
    snes.setType(str(snes_type or "vinewtonrsls"))
    snes.setTolerances(atol=float(tol_residual_inf), rtol=0.0, stol=0.0, max_it=int(max_iterations))
    ksp = snes.getKSP()
    if ksp is not None:
        ksp.setType("preonly")
        ksp.setTolerances(rtol=1.0e-12, atol=0.0, max_it=1)
        pc = ksp.getPC()
        if pc is not None:
            pc.setType("lu")
            pc.setFactorShift(
                PETSc.Mat.FactorShiftType.NONZERO,
                _DEFAULT_PC_FACTOR_SHIFT_AMOUNT,
            )
            pc.setFromOptions()
        ksp.setFromOptions()
    snes.setFromOptions()


def _prescribed_head_cells(prescribed_head_m_by_cell: np.ndarray | None) -> np.ndarray | None:
    return None if prescribed_head_m_by_cell is None else np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)


def _variable_bounds(mesh: BoussinesqMesh, prescribed_head_m_by_cell: np.ndarray | None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lower = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1).copy()
    upper = np.maximum(np.asarray(mesh.z_top_m, dtype=float).reshape(-1), lower)
    prescribed = (
        np.full(int(mesh.n_cells), np.nan, dtype=float)
        if prescribed_head_m_by_cell is None
        else np.asarray(prescribed_head_m_by_cell, dtype=float).reshape(-1)
    )
    prescribed_mask = np.isfinite(prescribed)
    if np.any(prescribed_mask):
        lower[prescribed_mask] = prescribed[prescribed_mask]
        upper[prescribed_mask] = prescribed[prescribed_mask]
    return lower, upper, prescribed_mask


def _clip_head_to_bounds(head_m: np.ndarray, *, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    return np.clip(np.asarray(head_m, dtype=float).reshape(-1), lower, upper)


def _obstacle_tolerance(tol_state_update_inf: float) -> float:
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
    head = np.asarray(head_m, dtype=float).reshape(-1)
    raw_residual = np.asarray(assembly.flow_residual_m3_s, dtype=float).reshape(-1)
    free_mask = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    surface_active = free_mask & (head >= np.asarray(physical_upper_m, dtype=float) - float(tol_h))
    bottom_active = free_mask & (head <= np.asarray(physical_lower_m, dtype=float) + float(tol_h))
    interior_free = free_mask & ~(surface_active | bottom_active)
    surface_reaction = np.where(surface_active, np.maximum(-raw_residual, 0.0), 0.0)
    bottom_reaction = np.where(bottom_active, np.maximum(raw_residual, 0.0), 0.0)
    area = np.asarray(mesh.cell_area_m2, dtype=float).reshape(-1)
    q_ex = np.divide(surface_reaction, area, out=np.zeros(int(mesh.n_cells), dtype=float), where=area > 0.0)
    q_dry = np.divide(bottom_reaction, area, out=np.zeros(int(mesh.n_cells), dtype=float), where=area > 0.0)
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
    }
    return (
        replace(
            assembly,
            saturation_excess_rate_m_s=q_ex,
            dry_deficit_rate_m_s=q_dry,
            flow_residual_m3_s=corrected_flow,
            residual_m3_s=corrected_residual,
            solver_residual=corrected_solver,
        ),
        diagnostics,
    )


def _projected_vi_residual(*, residual: np.ndarray, head_m: np.ndarray, lower_m: np.ndarray, upper_m: np.ndarray, prescribed_mask: np.ndarray, tol_h: float) -> np.ndarray:
    values = np.asarray(residual, dtype=float).reshape(-1)
    head = np.asarray(head_m, dtype=float).reshape(-1)
    lower = np.asarray(lower_m, dtype=float).reshape(-1)
    upper = np.asarray(upper_m, dtype=float).reshape(-1)
    projected = values.copy()
    free = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    lower_active = free & (head <= lower + float(tol_h))
    upper_active = free & (head >= upper - float(tol_h))
    interior = free & ~(lower_active | upper_active)
    projected[interior] = values[interior]
    projected[lower_active] = np.minimum(values[lower_active], 0.0)
    projected[upper_active] = np.maximum(values[upper_active], 0.0)
    return projected


def _free_residual_norm(*, residual: np.ndarray, head_m: np.ndarray, lower_m: np.ndarray, upper_m: np.ndarray, prescribed_mask: np.ndarray, tol_h: float) -> float:
    head = np.asarray(head_m, dtype=float).reshape(-1)
    free = ~np.asarray(prescribed_mask, dtype=bool).reshape(-1)
    interior = free & (head > np.asarray(lower_m, dtype=float) + float(tol_h)) & (head < np.asarray(upper_m, dtype=float) - float(tol_h))
    if not np.any(interior):
        return 0.0
    return residual_norm_inf(np.asarray(residual, dtype=float).reshape(-1)[interior])


def _step_diagnostic_record(*, ts, step_index: int, time_seconds: float, dt_seconds: float, raw_assembly: BoussinesqAssembly, head_m: np.ndarray, reaction_diagnostics: dict[str, Any], physical_lower_m: np.ndarray, physical_upper_m: np.ndarray) -> dict[str, Any]:
    snes = ts.getSNES()
    return {
        "ts_step_index": int(step_index),
        "t_seconds": float(time_seconds),
        "dt_seconds": float(dt_seconds),
        "converged_or_accepted": True,
        "ts_reason": int(ts.getConvergedReason()),
        "ts_reason_label": _ts_reason_label(int(ts.getConvergedReason())),
        "snes_reason": int(snes.getConvergedReason()),
        "snes_reason_label": _snes_reason_label(int(snes.getConvergedReason())),
        "ksp_reason": _linear_converged_reason(snes),
        "ksp_reason_label": _ksp_reason_label(_linear_converged_reason(snes)),
        "snes_iterations": int(snes.getIterationNumber()),
        "ksp_iterations": _linear_iteration_count(snes),
        "max_lower_violation_m": float(np.max(np.maximum(physical_lower_m - head_m, 0.0))),
        "max_upper_violation_m": float(np.max(np.maximum(head_m - physical_upper_m, 0.0))),
        "active_top_count": int(reaction_diagnostics.get("surface_active_cells", 0) or 0),
        "active_bottom_count": int(reaction_diagnostics.get("bottom_active_cells", 0) or 0),
        "free_count": int(reaction_diagnostics.get("free_cells", 0) or 0),
        "surface_reaction_total_m3_s": float(reaction_diagnostics.get("surface_reaction_total_m3_s", 0.0) or 0.0),
        "bottom_reaction_total_m3_s": float(reaction_diagnostics.get("bottom_reaction_total_m3_s", 0.0) or 0.0),
        "surface_reaction_total_m3": float(reaction_diagnostics.get("surface_reaction_total_m3_s", 0.0) or 0.0) * float(dt_seconds),
        "bottom_reaction_total_m3": float(reaction_diagnostics.get("bottom_reaction_total_m3_s", 0.0) or 0.0) * float(dt_seconds),
        "residual_norm_free": float(reaction_diagnostics.get("free_residual_norm_inf", 0.0) or 0.0),
        "residual_norm_projected": float(reaction_diagnostics.get("projected_vi_residual_norm_inf", 0.0) or 0.0),
        "h_min_m": float(np.min(head_m)) if head_m.size else None,
        "h_max_m": float(np.max(head_m)) if head_m.size else None,
        "residual_min_m3_s": float(np.min(raw_assembly.flow_residual_m3_s)) if raw_assembly.flow_residual_m3_s.size else None,
        "residual_max_m3_s": float(np.max(raw_assembly.flow_residual_m3_s)) if raw_assembly.flow_residual_m3_s.size else None,
        **_petsc_solver_configuration(snes),
    }


def _period_diagnostics(*, ts, snes, ts_reason: int, ts_reason_label: str, snes_reason: int, snes_reason_label: str, ts_steps_requested: int, dt_period_seconds: float, dt_initial_seconds: float, dt_min_seconds: float, dt_max_seconds: float, step_records: list[dict[str, Any]], reaction_diagnostics: dict[str, Any], residual_norm: float, head_m: np.ndarray, physical_lower_m: np.ndarray, physical_upper_m: np.ndarray, ts_vi_adapt: bool) -> dict[str, Any]:
    return {
        "ts_type": str(ts.getType()),
        "ts_adapt_type": "none" if not bool(ts_vi_adapt) else "petsc_default",
        "ts_vi_steps_per_period": int(ts_steps_requested),
        "ts_vi_adapt": bool(ts_vi_adapt),
        "ts_steps_taken": int(ts.getStepNumber()),
        "dt_period_seconds": float(dt_period_seconds),
        "dt_initial_seconds": float(dt_initial_seconds),
        "dt_min_seconds": float(dt_min_seconds),
        "dt_max_seconds": float(dt_max_seconds),
        "ts_converged_reason": int(ts_reason),
        "ts_converged_reason_label": str(ts_reason_label),
        "snes_converged_reason": int(snes_reason),
        "snes_converged_reason_label": str(snes_reason_label),
        "ksp_converged_reason": _linear_converged_reason(snes),
        "ksp_converged_reason_label": _ksp_reason_label(_linear_converged_reason(snes)),
        "total_snes_iterations": int(sum(int(row.get("snes_iterations", 0) or 0) for row in step_records)),
        "total_ksp_iterations": int(sum(int(row.get("ksp_iterations", 0) or 0) for row in step_records)),
        "max_snes_iterations_per_ts_step": _max_int(step_records, "snes_iterations"),
        "max_ksp_iterations_per_ts_step": _max_int(step_records, "ksp_iterations"),
        "max_violation_lower_m": float(np.max(np.maximum(physical_lower_m - head_m, 0.0))),
        "max_violation_upper_m": float(np.max(np.maximum(head_m - physical_upper_m, 0.0))),
        "projected_vi_residual_norm_inf": float(residual_norm),
        "ts_vi_step_details": list(step_records),
        "ts_vi_rate_forcing_rescaled": False,
        **reaction_diagnostics,
        **_petsc_solver_configuration(snes),
    }


def _petsc_solver_configuration(snes) -> dict[str, Any]:
    values: dict[str, Any] = {
        "petsc_options": os.environ.get("PETSC_OPTIONS"),
        "pc_factor_shift_type": _DEFAULT_PC_FACTOR_SHIFT_TYPE,
        "pc_factor_shift_amount": _DEFAULT_PC_FACTOR_SHIFT_AMOUNT,
    }
    try:
        values["snes_type"] = snes.getType()
        ksp = snes.getKSP()
        values["ksp_type"] = ksp.getType()
        pc = ksp.getPC()
        values["pc_type"] = pc.getType()
        if hasattr(pc, "getFactorShiftType"):
            values["pc_factor_shift_type"] = str(pc.getFactorShiftType())
        if hasattr(pc, "getFactorShiftAmount"):
            values["pc_factor_shift_amount"] = float(pc.getFactorShiftAmount())
    except Exception:
        pass
    return values


def _linear_iteration_count(snes) -> int:
    try:
        return int(snes.getLinearSolveIterations())
    except Exception:
        return 0


def _linear_converged_reason(snes) -> int:
    try:
        return int(snes.getKSP().getConvergedReason())
    except Exception:
        return 0


def _ksp_reason_label(reason: int) -> str:
    labels = {2: "KSP_CONVERGED_RTOL_NORMAL", 3: "KSP_CONVERGED_ATOL_NORMAL", -3: "KSP_DIVERGED_ITS", -11: "KSP_DIVERGED_PC_FAILED", 0: "KSP_CONVERGED_ITERATING"}
    return labels.get(int(reason), f"KSP_REASON_{int(reason)}")


def _max_int(rows: list[dict[str, Any]], key: str) -> int:
    values = [int(row.get(key, 0) or 0) for row in rows]
    return int(max(values)) if values else 0


def _normalize_step_count(value: int) -> int:
    count = int(value)
    if count <= 0:
        raise ValueError(f"ts_vi_steps_per_period must be positive; got {count}.")
    return count


def _ts_reason_label(reason: int) -> str:
    labels = {0: "TS_CONVERGED_ITERATING", 1: "TS_CONVERGED_TIME", 2: "TS_CONVERGED_ITS", 3: "TS_CONVERGED_USER", 4: "TS_CONVERGED_EVENT", -1: "TS_DIVERGED_NONLINEAR_SOLVE", -2: "TS_DIVERGED_STEP_REJECTED", -99: "TS_DIVERGED_EXCEPTION"}
    return labels.get(int(reason), f"TS_REASON_{int(reason)}")


__all__ = ["solve_steady_problem", "solve_transient_step"]
