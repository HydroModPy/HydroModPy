"""Picard/VI cycles and strict VI obstacle assembly."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np

from hydromodpy.solver.boussinesq.assembly.fluxes import (
    accumulate_internal_flux_residual,
    harmonic_conductivity,
    internal_edge_flux_from_head,
    saturated_thickness_from_head,
)
from hydromodpy.solver.boussinesq.assembly.inputs import (
    as_cell_vector,
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
from hydromodpy.solver.boussinesq.runtimes.picard.diagnostics import (
    DRY_THICKNESS_TOL_M,
    MIN_DISTANCE_M,
    PicardViCycleOptions,
    PicardViCycleRecord,
    clip_head,
    free_residual_norm,
    jsonable,
    obstacle_tolerance,
    physical_bounds,
    prescribed_head_cells,
    quantiles,
)


def strict_drainage_conductance(
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


def strict_drainage_flux(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    drainage_conductance_m2_s: np.ndarray | float | None,
) -> np.ndarray:
    """Return the drainage flux for cells whose head exceeds z_top."""
    conductance = strict_drainage_conductance(
        mesh,
        drainage_conductance_m2_s=drainage_conductance_m2_s,
    )
    return conductance * np.maximum(np.asarray(head_m, dtype=float) - mesh.z_top_m, 0.0)


def assemble_strict_steady_residual(
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
    prescribed = prescribed_head_cells(prescribed_head_m_by_cell, n_cells=n_cells)
    prescribed_mask = np.isfinite(prescribed)
    if np.any(prescribed_mask):
        head[prescribed_mask] = prescribed[prescribed_mask]

    thickness = saturated_thickness_from_head(mesh, head)
    transmissivity = np.asarray(mesh.hydraulic_conductivity_m_s, dtype=float) * thickness
    internal_flux = internal_edge_flux_from_head(mesh, head)
    internal_residual = accumulate_internal_flux_residual(mesh, internal_flux)
    recharge = as_cell_vector(recharge_rate_m_s, n_cells=n_cells, label="recharge_rate_m_s")
    well_flux = as_cell_vector(well_flux_m3_s, n_cells=n_cells, label="well_flux_m3_s")
    drainage = strict_drainage_flux(
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


def runtime_result_from_raw_assembly(
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
    """Reconstruct an obstacle-aware runtime result from a raw residual assembly."""
    tol_h = obstacle_tolerance(inputs)
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
        "free_residual_norm_inf": free_residual_norm(
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


def strict_result_for_head(
    inputs: SteadySolveInputs,
    head_m: np.ndarray,
    *,
    backend_name: str,
    iterations: int,
    termination_reason: str,
    extra_diagnostics: dict[str, Any] | None = None,
) -> RuntimeSolveResult:
    """Build a strict-residual runtime result starting from a clipped head guess."""
    mesh = inputs.mesh
    prescribed = prescribed_head_cells(inputs.prescribed_head_m_by_cell, n_cells=mesh.n_cells)
    lower, upper, prescribed_mask = physical_bounds(mesh, prescribed)
    head = clip_head(
        np.asarray(head_m, dtype=float).reshape(-1),
        lower=lower,
        upper=upper,
        project_bounds=True,
    )
    raw = assemble_strict_steady_residual(
        mesh,
        head,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
    )
    return runtime_result_from_raw_assembly(
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


def strict_thickness_and_derivative(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return clipped saturated thickness and the indicator derivative."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    bottom = np.asarray(mesh.z_bottom_m, dtype=float).reshape(-1)
    top = np.asarray(mesh.z_top_m, dtype=float).reshape(-1)
    max_thickness = np.maximum(top - bottom, 0.0)
    raw = head - bottom
    thickness = np.clip(raw, 0.0, max_thickness)
    derivative = np.where((raw > 0.0) & (raw < max_thickness), 1.0, 0.0)
    return thickness, derivative


def strict_jacobian_triplets(
    mesh: BoussinesqMesh,
    head_m: np.ndarray,
    *,
    prescribed_head_m_by_cell: np.ndarray | None,
    drainage_conductance_m2_s: np.ndarray | float | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Build COO triplets for the strict steady Jacobian."""
    head = np.asarray(head_m, dtype=float).reshape(-1)
    n_cells = int(mesh.n_cells)
    prescribed = prescribed_head_cells(prescribed_head_m_by_cell, n_cells=n_cells)
    prescribed_mask = np.isfinite(prescribed)
    thickness, derivative = strict_thickness_and_derivative(mesh, head)
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
        distance = max(float(mesh.edge_distance_m[edge_index]), MIN_DISTANCE_M)
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

    conductance = strict_drainage_conductance(
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


def strict_snes_diagnostics(
    snes,
    *,
    raw_assembly: BoussinesqAssembly,
    head: np.ndarray,
    lower: np.ndarray,
    upper: np.ndarray,
    prescribed_mask: np.ndarray,
    inputs: SteadySolveInputs,
) -> dict[str, Any]:
    """Return SNES diagnostics for the strict PETSc VI obstacle check."""
    reason = int(snes.getConvergedReason())
    tol_h = obstacle_tolerance(inputs)
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
        "free_residual_norm_inf": free_residual_norm(
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


def solve_strict_vi_obstacle(  # noqa: PLR0915
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
    prescribed = prescribed_head_cells(inputs.prescribed_head_m_by_cell, n_cells=n_cells)
    lower, upper, prescribed_mask = physical_bounds(mesh, prescribed)
    head0 = clip_head(
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

    current_assembly = assemble_strict_steady_residual(
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
        current_assembly = assemble_strict_steady_residual(
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
        data, row_indices, col_indices = strict_jacobian_triplets(
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
    raw_assembly = assemble_strict_steady_residual(
        mesh,
        head,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
    )
    base_result = runtime_result_from_raw_assembly(
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
        extra_diagnostics=strict_snes_diagnostics(
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
        tol_h=obstacle_tolerance(inputs),
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


def accept_failed_vi_cycle_candidate(
    *,
    picard_result: RuntimeSolveResult,
    vi_result: RuntimeSolveResult,
    options: PicardViCycleOptions,
) -> bool:
    """Return True when a failed VI candidate is acceptable for the current cycle."""
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


def cycle_record(
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
    """Return a PicardViCycleRecord for one cycle."""
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
        physically_dry_count=int(np.count_nonzero(thickness <= DRY_THICKNESS_TOL_M)),
        note=str(note),
    )


def cycle_summary(
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
    """Return a JSON-friendly summary of the Picard/VI cycle run."""
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
        "cells_physically_dry_count": int(np.count_nonzero(thickness <= DRY_THICKNESS_TOL_M)),
        "h_min": float(np.min(head)) if head.size else math.nan,
        "h_max": float(np.max(head)) if head.size else math.nan,
        "physical_saturated_thickness_quantiles": quantiles(thickness),
        "transmissivity_quantiles": quantiles(transmissivity),
        "runtime_seconds": float(runtime_seconds),
        "cycle_options": jsonable(options.__dict__),
    }
    if records:
        summary["last_cycle"] = jsonable(records[-1].__dict__)
    return summary


def bounded_picard_vi_cycles(  # noqa: PLR0915
    inputs: SteadySolveInputs,
    *,
    cycle_options: PicardViCycleOptions | None = None,
    diagnostics_dir: str | Path | None = None,
    case_id: str = "",
) -> RuntimeSolveResult:
    """Alternate strict Picard blocks and strict VI correction attempts."""
    from hydromodpy.solver.boussinesq.runtimes.picard.io import (
        write_picard_vi_cycle_diagnostics,
    )
    from hydromodpy.solver.boussinesq.runtimes.picard.lscheme import bounded_picard_lscheme

    options = cycle_options or PicardViCycleOptions()
    start = time.perf_counter()
    mesh = inputs.mesh
    prescribed = prescribed_head_cells(inputs.prescribed_head_m_by_cell, n_cells=mesh.n_cells)
    lower, upper, prescribed_mask = physical_bounds(mesh, prescribed)
    head = clip_head(
        np.asarray(inputs.head_initial_guess_m, dtype=float).reshape(-1),
        lower=lower,
        upper=upper,
        project_bounds=True,
    )
    current_result = strict_result_for_head(
        inputs,
        head,
        backend_name="bounded_picard_vi_cycles",
        iterations=0,
        termination_reason="Picard/VI cycle initial residual",
        extra_diagnostics={"method": "bounded_picard_vi_cycles"},
    )
    # Silence "lower/upper/prescribed_mask unused": kept for parity with the
    # earlier signature and to match strict_result_for_head's contract.
    del lower, upper, prescribed_mask
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
            vi_result = solve_strict_vi_obstacle(
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
        elif vi_result is not None and accept_failed_vi_cycle_candidate(
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
            cycle_record(
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
            final_check = solve_strict_vi_obstacle(
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
    summary = cycle_summary(
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
