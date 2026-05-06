"""Transient driver helpers for the Boussinesq solver."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.solver.boussinesq.drivers.forcing import (
    apply_ocean_drainage_mask,
    resolve_runtime_forcing_by_period,
)
from hydromodpy.solver.boussinesq.drivers.state import (
    TransientRuntimeHistory,
    build_transient_activity_flags,
)
from hydromodpy.solver.boussinesq.runtime_contract import TransientStepInputs
from hydromodpy.solver.boussinesq.runtime_summary import record_runtime_backend_summary

if TYPE_CHECKING:
    from hydromodpy.solver.boussinesq.boussinesq import Boussinesq


def run_transient_runtime(solver: Boussinesq) -> bool:
    """Advance the head state over all launcher stress periods."""
    if solver.mesh is None:
        raise RuntimeError("Mesh must be built before running the runtime.")
    if solver.state is None:
        raise RuntimeError("Initial state must exist before time integration.")
    contract = solver._resolve_solver_contract()
    runtime_backend = contract.runtime_backend
    record_runtime_backend_summary(solver, contract)
    solver._assert_runtime_mesh_size_supported(runtime_backend)

    period_lengths = tuple(
        float(value) for value in (getattr(solver.time_grid, "period_lengths_seconds", ()) or ())
    )
    if not period_lengths:
        return True

    nper = len(period_lengths)
    runtime_forcing = resolve_runtime_forcing_by_period(solver, nper=nper)
    recharge_series_m_s = runtime_forcing.recharge_series_m_s
    well_flux_by_period_m3_s = runtime_forcing.well_flux_by_period_m3_s
    boundary_forcing = runtime_forcing
    dirichlet_supports_by_period = boundary_forcing.dirichlet_supports_by_period
    prescribed_heads_by_period = boundary_forcing.prescribed_heads_by_period
    boundary_heads_by_period = boundary_forcing.boundary_heads_by_period
    ocean_supported_cell_masks = boundary_forcing.ocean_supported_cell_masks
    drainage_conductance_series_m2_s = boundary_forcing.drainage_conductance_series_m2_s

    head_prev = np.asarray(solver.state.head_m, dtype=float)
    history = TransientRuntimeHistory.initialize(
        mesh=solver.mesh,
        head_m=head_prev,
        saturated_thickness_m=np.asarray(
            solver.state.saturated_thickness_m,
            dtype=float,
        ),
    )
    nonlinear_iterations: list[int] = []
    converged_by_period: list[bool] = []
    runtime_period_diagnostics: list[dict[str, object]] = []
    runtime_substep_diagnostics: list[dict[str, object]] = []
    runtime_ts_step_diagnostics: list[dict[str, object]] = []
    last_residual_norm = 0.0

    for kper, dt_seconds in enumerate(period_lengths):
        ocean_supported_cell_mask = np.asarray(
            ocean_supported_cell_masks[kper],
            dtype=bool,
        )
        drainage_conductance = apply_ocean_drainage_mask(
            n_cells=solver.mesh.n_cells,
            drainage_value_m2_s=float(drainage_conductance_series_m2_s[kper]),
            ocean_supported_cell_mask=ocean_supported_cell_mask,
        )
        step = runtime_backend.solve_transient_step(
            TransientStepInputs(
                mesh=solver.mesh,
                head_prev_m=head_prev,
                dt_seconds=float(dt_seconds),
                head_initial_guess_m=head_prev,
                recharge_rate_m_s=recharge_series_m_s[kper],
                well_flux_m3_s=well_flux_by_period_m3_s[kper],
                prescribed_head_m_by_cell=prescribed_heads_by_period[kper],
                drainage_conductance_m2_s=drainage_conductance,
                options=solver._runtime_options(),
            )
        )
        nonlinear_iterations.append(int(step.iterations))
        converged_by_period.append(bool(step.converged))
        head_prev = np.asarray(step.head_m, dtype=float)
        last_residual_norm = float(step.residual_norm_inf)
        solver.runtime_summary["last_termination_reason"] = str(step.termination_reason)
        if step.diagnostics:
            period_diagnostics = dict(step.diagnostics)
            period_diagnostics["period_index"] = int(kper)
            runtime_period_diagnostics.append(period_diagnostics)
            raw_substeps = step.diagnostics.get("vi_substep_details")
            if isinstance(raw_substeps, list):
                for item in raw_substeps:
                    if isinstance(item, dict):
                        substep_diagnostics = dict(item)
                        substep_diagnostics["period_index"] = int(kper)
                        runtime_substep_diagnostics.append(substep_diagnostics)
            raw_ts_steps = step.diagnostics.get("ts_vi_step_details")
            if isinstance(raw_ts_steps, list):
                for item in raw_ts_steps:
                    if isinstance(item, dict):
                        ts_step_diagnostics = dict(item)
                        ts_step_diagnostics["period_index"] = int(kper)
                        runtime_ts_step_diagnostics.append(ts_step_diagnostics)
            for key, value in step.diagnostics.items():
                solver.runtime_summary[f"last_{key}"] = value
        history.append_step(
            mesh=solver.mesh,
            head_m=head_prev,
            assembly=step.assembly,
            prescribed_head_m_by_cell=np.asarray(
                prescribed_heads_by_period[kper],
                dtype=float,
            ),
            boundary_head_m_by_edge=np.asarray(
                boundary_heads_by_period[kper],
                dtype=float,
            ),
        )
        if not step.converged:
            solver.state = history.build_runtime_state(
                period_lengths_seconds=period_lengths,
                nonlinear_iterations=tuple(nonlinear_iterations),
                converged_by_period=tuple(converged_by_period),
            )
            solver.runtime_summary["last_residual_norm_inf"] = last_residual_norm
            solver.runtime_summary["n_periods"] = nper
            if runtime_period_diagnostics:
                solver.runtime_summary["runtime_period_diagnostics"] = runtime_period_diagnostics
            if runtime_substep_diagnostics:
                solver.runtime_summary["runtime_substep_diagnostics"] = (
                    runtime_substep_diagnostics
                )
            if runtime_ts_step_diagnostics:
                solver.runtime_summary["runtime_ts_step_diagnostics"] = (
                    runtime_ts_step_diagnostics
                )
            solver.runtime_summary.update(
                build_transient_activity_flags(
                    recharge_series_m_s=recharge_series_m_s,
                    well_flux_by_period_m3_s=well_flux_by_period_m3_s,
                    dirichlet_supports_by_period=dirichlet_supports_by_period,
                    prescribed_heads_by_period=prescribed_heads_by_period,
                    ocean_supported_cell_masks=ocean_supported_cell_masks,
                    drainage_conductance_series_m2_s=drainage_conductance_series_m2_s,
                )
            )
            return False

    solver.state = history.build_runtime_state(
        period_lengths_seconds=period_lengths,
        nonlinear_iterations=tuple(nonlinear_iterations),
        converged_by_period=tuple(converged_by_period),
    )
    solver.runtime_summary["n_periods"] = nper
    solver.runtime_summary["last_residual_norm_inf"] = last_residual_norm
    if runtime_period_diagnostics:
        solver.runtime_summary["runtime_period_diagnostics"] = runtime_period_diagnostics
    if runtime_substep_diagnostics:
        solver.runtime_summary["runtime_substep_diagnostics"] = runtime_substep_diagnostics
    if runtime_ts_step_diagnostics:
        solver.runtime_summary["runtime_ts_step_diagnostics"] = runtime_ts_step_diagnostics
    solver.runtime_summary.update(
        build_transient_activity_flags(
            recharge_series_m_s=recharge_series_m_s,
            well_flux_by_period_m3_s=well_flux_by_period_m3_s,
            dirichlet_supports_by_period=dirichlet_supports_by_period,
            prescribed_heads_by_period=prescribed_heads_by_period,
            ocean_supported_cell_masks=ocean_supported_cell_masks,
            drainage_conductance_series_m2_s=drainage_conductance_series_m2_s,
        )
    )
    return True


__all__ = ["run_transient_runtime"]
