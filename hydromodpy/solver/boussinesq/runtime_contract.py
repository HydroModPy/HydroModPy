"""Common runtime contracts for Boussinesq nonlinear solvers.

The philosophy of this module is simple: every runtime backend should receive
the same physical inputs and should return the same kind of result object.

That separation is important because it lets the driver switch from the local
Newton loop to SciPy root finding without touching the physics assembly or the
post-processing code.

Dirichlet representation - known systematic boundary bias
---------------------------------------------------------

The canonical Dirichlet input below is ``prescribed_head_m_by_cell`` - the
head value is assigned directly to the unknown of the boundary cell, not to
the boundary edge midpoint. This is a deliberate simplification (one fewer
unknown, no interface equation) inherited from the v0.6 runtime refactor
(commit ``c4cb92b7``, J.-R. de Dreuzy, 2026-04-17) and enforced as
mutually exclusive with ``boundary_head_m_by_edge`` at
``assembly/inputs.py:105``.

Trade-off to be aware of when interpreting solver output:

* On problems with strong head gradients near a Dirichlet frontier, the
  boundary-cell head is pinned at the Dirichlet value but the exact solution
  at the cell centroid differs from the edge value by ``O(grad h · dx/2)``.
* Empirically, on the Dupuit analytical case
  (``validation_cases/analytical/steady/dupuit_fixed_head_1d``,
  :math:`L = 400\\,\\text{m}`, :math:`h = 10 \\to 5\\,\\text{m}`), this
  produces up to **~32 mm** of signed residual at the boundary cells
  (RMSE ≈ **13.6 mm**, well within the 50 mm tolerance of the boussinesq
  profile; the MODFLOW edge-Dirichlet tolerance is sub-mm by comparison).
* If sub-mm boundary accuracy is required, refine the mesh near the
  Dirichlet boundary or switch the backend-level assembly to use the
  ``boundary_head_m_by_edge`` path (still wired in ``assembly/inputs.py``).

When regenerating regression goldens under this contract, expect
~0.5 % systematic head shifts versus any pre-2026-04-17 baseline.
"""

from __future__ import annotations

from dataclasses import dataclass

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

    regularization_radius: float
    max_iterations: int
    tol_residual_inf: float
    tol_state_update_inf: float = 1.0e-9
    fd_rel_step: float = 1.0e-7
    min_damping: float = 1.0e-4


@dataclass(frozen=True, kw_only=True)
class TransientStepInputs:
    """Inputs for one fully implicit transient step.

    ``head_prev_m`` is the accepted state from the previous period. The runtime
    solves for the new head field ``head^{n+1}`` that drives the transient
    residual to zero over ``dt_seconds``.

    ``prescribed_head_m_by_cell`` is the canonical runtime Dirichlet view.
    See the module-level note on the "systematic boundary bias" trade-off
    this choice introduces (cell-centroid vs edge-midpoint pinning).
    """

    mesh: BoussinesqMesh
    head_prev_m: np.ndarray
    dt_seconds: float
    options: NonlinearRuntimeOptions
    head_initial_guess_m: np.ndarray | None = None
    recharge_rate_m_s: np.ndarray | float | None = None
    well_flux_m3_s: np.ndarray | float | None = None
    prescribed_head_m_by_cell: np.ndarray | None = None
    drainage_conductance_m2_s: np.ndarray | float | None = None


@dataclass(frozen=True, kw_only=True)
class SteadySolveInputs:
    """Inputs for one steady nonlinear balance.

    In the steady case there is no storage term, so the runtime only needs an
    initial head guess plus the forcing and boundary data for the current
    stationary problem.

    ``prescribed_head_m_by_cell`` is the canonical runtime Dirichlet view.
    See the module-level note on the "systematic boundary bias" trade-off
    this choice introduces (cell-centroid vs edge-midpoint pinning).
    """

    mesh: BoussinesqMesh
    head_initial_guess_m: np.ndarray
    options: NonlinearRuntimeOptions
    recharge_rate_m_s: np.ndarray | float | None = None
    well_flux_m3_s: np.ndarray | float | None = None
    prescribed_head_m_by_cell: np.ndarray | None = None
    drainage_conductance_m2_s: np.ndarray | float | None = None


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
