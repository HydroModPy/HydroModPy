"""Steady driver helpers for the Boussinesq solver."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from hydromodpy.solver.boussinesq.driver_forcing import (
    apply_ocean_drainage_mask,
    resolve_boundary_forcing_by_period,
)
from hydromodpy.solver.boussinesq.driver_state import build_steady_runtime_state
from hydromodpy.solver.boussinesq.runtime_contract import SteadySolveInputs

if TYPE_CHECKING:
    from hydromodpy.solver.boussinesq.boussinesq import Boussinesq


def run_steady_runtime(solver: "Boussinesq") -> bool:
    """Solve one steady nonlinear balance on the selected backend."""
    if solver.mesh is None:
        raise RuntimeError("Mesh must be built before running the runtime.")
    if solver.state is None:
        raise RuntimeError("Initial state must exist before steady solve.")
    contract = solver._resolve_solver_contract()
    runtime_backend = contract.runtime_backend
    solver._record_runtime_backend_summary(contract)
    solver._assert_runtime_mesh_size_supported(runtime_backend)

    recharge_rate_m_s = solver._resolve_recharge_series(1)[0]
    well_flux_m3_s = np.asarray(solver._resolve_well_flux_by_period(1)[0], dtype=float)
    boundary_forcing = resolve_boundary_forcing_by_period(solver, nper=1)
    dirichlet_supports = boundary_forcing.dirichlet_supports_by_period[0]
    boundary_heads_by_edge = boundary_forcing.boundary_heads_by_period[0]
    prescribed_head_m_by_cell = boundary_forcing.prescribed_heads_by_period[0]
    ocean_supported_cell_mask = boundary_forcing.ocean_supported_cell_masks[0]
    drainage_value = float(boundary_forcing.drainage_conductance_series_m2_s[0])
    drainage_conductance = apply_ocean_drainage_mask(
        n_cells=solver.mesh.n_cells,
        drainage_value_m2_s=drainage_value,
        ocean_supported_cell_mask=ocean_supported_cell_mask,
    )

    steady = runtime_backend.solve_steady_problem(
        SteadySolveInputs(
            mesh=solver.mesh,
            head_initial_guess_m=np.asarray(solver.state.head_m, dtype=float),
            recharge_rate_m_s=recharge_rate_m_s,
            well_flux_m3_s=well_flux_m3_s,
            prescribed_head_m_by_cell=prescribed_head_m_by_cell,
            drainage_conductance_m2_s=drainage_conductance,
            options=solver._runtime_options(),
        )
    )
    solver.state = build_steady_runtime_state(
        mesh=solver.mesh,
        head_m=np.asarray(steady.head_m, dtype=float),
        assembly=steady.assembly,
        prescribed_head_m_by_cell=prescribed_head_m_by_cell,
        boundary_head_m_by_edge=boundary_heads_by_edge,
        nonlinear_iterations=int(steady.iterations),
        converged=bool(steady.converged),
    )
    solver.runtime_summary["steady_mode"] = f"nonlinear_{runtime_backend.name}"
    solver.runtime_summary["steady_residual_norm_inf"] = float(
        steady.residual_norm_inf
    )
    solver.runtime_summary["steady_nonlinear_iterations"] = int(steady.iterations)
    solver.runtime_summary["steady_termination_reason"] = str(
        steady.termination_reason
    )
    solver.runtime_summary["active_recharge"] = solver._has_active_recharge_payload(
        (recharge_rate_m_s,)
    )
    solver.runtime_summary["active_wells"] = bool(np.any(well_flux_m3_s != 0.0))
    solver.runtime_summary["active_prescribed_head_bc"] = bool(len(dirichlet_supports) > 0)
    solver.runtime_summary["active_dirichlet_bc"] = bool(
        solver.runtime_summary["active_prescribed_head_bc"]
    )
    solver.runtime_summary["active_ocean"] = bool(np.any(ocean_supported_cell_mask))
    solver.runtime_summary["active_drainage"] = bool(drainage_value != 0.0)
    return bool(steady.converged)


__all__ = ["run_steady_runtime"]
