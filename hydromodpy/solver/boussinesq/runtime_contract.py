"""Common runtime contracts for Boussinesq nonlinear solvers.

The philosophy of this module is simple: every runtime backend should receive
the same physical inputs and should return the same kind of result object.

That separation is important because it lets the driver switch from the local
Newton loop to SciPy root finding without touching the physics assembly or the
post-processing code.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from hydromodpy.solver.boussinesq.assembly import BoussinesqAssembly
from hydromodpy.solver.boussinesq.mesh import BoussinesqMesh


@dataclass(frozen=True)
class NonlinearRuntimeOptions:
    """Shared nonlinear-solve options used by all Boussinesq runtimes.

    The most important rule is that ``tol_residual_inf`` stays the common
    convergence criterion across backends. A backend may use an extra stopping
    rule on the state update, but it should still satisfy the residual
    tolerance before advertising success.
    """

    regularization_radius: float = 0.05
    max_iterations: int = 20
    tol_residual_inf: float = 1.0e-9
    tol_state_update_inf: float = 1.0e-9
    fd_rel_step: float = 1.0e-7
    min_damping: float = 1.0e-4


@dataclass(frozen=True)
class TransientStepInputs:
    """Inputs for one fully implicit transient step.

    ``head_prev_m`` is the accepted state from the previous period. The runtime
    solves for the new head field ``head^{n+1}`` that drives the transient
    residual to zero over ``dt_seconds``.
    """

    mesh: BoussinesqMesh
    head_prev_m: np.ndarray
    dt_seconds: float
    head_initial_guess_m: np.ndarray | None = None
    recharge_rate_m_s: np.ndarray | float | None = None
    well_flux_m3_s: np.ndarray | float | None = None
    imposed_head_m_by_edge: np.ndarray | None = None
    drainage_conductance_m2_s: np.ndarray | float | None = None
    options: NonlinearRuntimeOptions = field(
        default_factory=NonlinearRuntimeOptions
    )


@dataclass(frozen=True)
class SteadySolveInputs:
    """Inputs for one steady nonlinear balance.

    In the steady case there is no storage term, so the runtime only needs an
    initial head guess plus the forcing and boundary data for the current
    stationary problem.
    """

    mesh: BoussinesqMesh
    head_initial_guess_m: np.ndarray
    recharge_rate_m_s: np.ndarray | float | None = None
    well_flux_m3_s: np.ndarray | float | None = None
    imposed_head_m_by_edge: np.ndarray | None = None
    drainage_conductance_m2_s: np.ndarray | float | None = None
    options: NonlinearRuntimeOptions = field(
        default_factory=NonlinearRuntimeOptions
    )


@dataclass(frozen=True)
class RuntimeSolveResult:
    """Normalized output returned by any Boussinesq runtime backend.

    The ``assembly`` field is intentionally returned alongside ``head_m`` so
    callers can reuse the already assembled fluxes, transmissivities and
    residuals instead of recomputing them during post-processing.
    """

    head_m: np.ndarray
    assembly: BoussinesqAssembly
    converged: bool
    iterations: int
    residual_norm_inf: float
    backend_name: str
    termination_reason: str = ""


__all__ = [
    "NonlinearRuntimeOptions",
    "RuntimeSolveResult",
    "SteadySolveInputs",
    "TransientStepInputs",
]
