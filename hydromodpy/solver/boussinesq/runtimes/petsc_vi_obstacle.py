"""Experimental PETSc SNESVI runtime for a head-only obstacle formulation.

This backend is intentionally separate from ``petsc_mixed``. It does not put
``q_ex`` or ``q_dry`` in the PETSc state vector and it does not use
Fischer-Burmeister residuals. PETSc solves only for ``h`` with explicit bounds
``z_bottom <= h <= z_top`` by default; after convergence the remaining
groundwater balance residual on active bounds is reconstructed as a surface or
bottom reaction. With an explicit positive Cauchy drainage conductance, the
upper obstacle is relaxed and the drainage flux term carries the top exchange.

This module is the public facade for the ``petsc_vi`` sub-package, which
splits the runtime in three concerns:

- ``petsc_vi.petsc``: pure PETSc utility helpers (SNES configuration, diagnostics).
- ``petsc_vi.obstacle``: obstacle-specific math (clipping, reactions, projected residual).
- ``petsc_vi.vi``: VI orchestration (substeps, diagnostics, top-level SNESVI).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np

from hydromodpy.solver.boussinesq.assembly import (
    BoussinesqAssembly,
    assemble_steady_residual_with_saturation_excess,
)
from hydromodpy.solver.boussinesq.runtime_contract import (
    RuntimeSolveResult,
    SteadySolveInputs,
    TransientStepInputs,
)
from hydromodpy.solver.boussinesq.runtimes.dry_equilibrium import (
    detect_dry_equilibrium,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.obstacle import (
    clip_head_to_bounds as _clip_head_to_bounds,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.obstacle import (
    obstacle_tolerance as _obstacle_tolerance,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.obstacle import (
    prescribed_head_cells as _prescribed_head_cells,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.obstacle import (
    projected_vi_residual as _projected_vi_residual,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.obstacle import (
    reconstruct_obstacle_reactions as _reconstruct_obstacle_reactions,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.petsc import (
    accept_failed_snes_by_projected_tolerance as _accept_failed_snes_by_projected_tolerance,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.petsc import (
    configure_vi_snes as _configure_vi_snes,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.vi import (
    attempt_diagnostic_record as _attempt_diagnostic_record,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.vi import (
    dry_equilibrium_result as _dry_equilibrium_result,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.vi import (
    normalize_substep_count as _normalize_substep_count,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.vi import (
    period_substep_diagnostics as _period_substep_diagnostics,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.vi import (
    restored_transient_failure_result as _restored_transient_failure_result,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.vi import (
    solve_transient_vi_substep as _solve_transient_vi_substep,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.vi import (
    solve_vi_obstacle_problem as _solve_vi_obstacle_problem,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.vi import (
    substep_attempt_counts as _substep_attempt_counts,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.vi import (
    substep_diagnostic_record as _substep_diagnostic_record,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.vi import (
    sum_attempt_iterations as _sum_attempt_iterations,
)
from hydromodpy.solver.boussinesq.runtimes.petsc_vi.vi import (
    sum_substep_iterations as _sum_substep_iterations,
)
from hydromodpy.solver.boussinesq.runtimes.vi_bounds import (
    variable_bounds as _variable_bounds,
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
                head_initial if attempt_index == 0 and substep_index == 0 else head_current
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

    dry_equilibrium = detect_dry_equilibrium(
        inputs.mesh,
        recharge_rate_m_s=inputs.recharge_rate_m_s,
        well_flux_m3_s=inputs.well_flux_m3_s,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
        tol_bottom_vi=max(float(inputs.options.tol_residual_inf), 1.0e-12),
    )
    if dry_equilibrium.detected:
        return _dry_equilibrium_result(
            mesh=inputs.mesh,
            assembly_for=_assembly_for,
            head_m=dry_equilibrium.head_m,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=inputs.drainage_conductance_m2_s,
            tol_state_update_inf=float(inputs.options.tol_state_update_inf),
            backend_name="petsc",
            dry_diagnostics=dry_equilibrium.diagnostics,
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


__all__ = [
    "_accept_failed_snes_by_projected_tolerance",
    "_clip_head_to_bounds",
    "_configure_vi_snes",
    "_obstacle_tolerance",
    "_projected_vi_residual",
    "_reconstruct_obstacle_reactions",
    "_variable_bounds",
    "solve_steady_problem",
    "solve_transient_step",
]
