"""MMS benchmark: 1D diffusion transient with ``exp(-pi^2 D t) sin(pi x)``.

Governing PDE on ``[0, 1]`` with Dirichlet 0/0 and initial condition
``h(x, 0) = sin(pi x)``::

    h_t - D h_xx = 0

The manufactured solution ``h(x, t) = exp(-pi^2 D t) sin(pi x)`` is an
exact eigenfunction of the Laplacian with no forcing. The discretisation
combines the standard second-order centred-space stencil with either
backward Euler (first-order in time) or Crank-Nicolson (second-order in
time) for the temporal update. Two refinement studies are run:

* **space** — ``dx`` refined with Crank-Nicolson in time so the temporal
  error stays small enough for the spatial slope to emerge. Expected
  slope ~2.
* **time**  — ``dx`` held fine, ``dt`` refined under backward Euler.
  Expected slope ~1 (see ``tests/TOLERANCES.md`` row 10).
"""

from __future__ import annotations

import numpy as np
import pytest

from .conftest import l2_error, run_mms_convergence

D = 1.0  # diffusion coefficient (unit strength keeps numbers O(1))
T_FINAL = 0.1  # final time — several e-folding times for D = 1
LAMBDA = (np.pi**2) * D


def _exact_solution(x: np.ndarray, t: float) -> np.ndarray:
    return np.exp(-LAMBDA * t) * np.sin(np.pi * x)


def _initial_condition(x: np.ndarray) -> np.ndarray:
    return np.sin(np.pi * x)


def _solve_diffusion_1d(
    n_cells: int,
    n_steps: int,
    *,
    scheme: str,
) -> tuple[np.ndarray, np.ndarray, float, float]:
    """Solve the 1D diffusion equation with ``scheme`` in ``{"be", "cn"}``.

    Returns ``(x, u_final, dx, dt)`` where ``x`` contains boundary nodes and
    ``u_final`` the solution at ``t = n_steps * dt`` on the same grid.
    Backward Euler (``"be"``) is first-order in time, Crank-Nicolson
    (``"cn"``) is second-order. The spatial stencil is centred second order
    in both cases.
    """
    if n_cells < 3:
        raise ValueError("n_cells must be >= 3 to estimate a spatial order")
    if n_steps < 1:
        raise ValueError("n_steps must be >= 1")
    if scheme not in {"be", "cn"}:
        raise ValueError(f"unknown scheme {scheme!r}: expected 'be' or 'cn'")
    dx = 1.0 / float(n_cells + 1)
    dt = T_FINAL / float(n_steps)
    x_interior = np.linspace(dx, 1.0 - dx, n_cells)
    r = D * dt / (dx * dx)
    lap_main = -2.0 * np.ones(n_cells)
    lap_off = np.ones(n_cells - 1)
    lap = np.diag(lap_main) + np.diag(lap_off, 1) + np.diag(lap_off, -1)
    identity = np.eye(n_cells)
    if scheme == "be":
        a_mat = identity - r * lap
        b_mat = identity
    else:  # Crank-Nicolson
        a_mat = identity - 0.5 * r * lap
        b_mat = identity + 0.5 * r * lap
    u = _initial_condition(x_interior).copy()
    for _ in range(n_steps):
        u = np.linalg.solve(a_mat, b_mat @ u)
    x = np.concatenate(([0.0], x_interior, [1.0]))
    u_final = np.concatenate(([0.0], u, [0.0]))
    return x, u_final, dx, dt


def _make_space_case(n_steps_fine: int):
    def case(n_cells: int) -> tuple[float, float]:
        x, u_num, dx, _ = _solve_diffusion_1d(n_cells, n_steps_fine, scheme="cn")
        err = l2_error(u_num, _exact_solution(x, T_FINAL), h=dx)
        return dx, err

    return case


def _make_time_case(n_cells_fine: int):
    def case(n_steps: int) -> tuple[float, float]:
        x, u_num, _, dt = _solve_diffusion_1d(n_cells_fine, n_steps, scheme="be")
        # Use a fixed reference spacing for the L2 norm so only dt moves.
        err = l2_error(u_num, _exact_solution(x, T_FINAL), h=1.0 / float(n_cells_fine + 1))
        return dt, err

    return case


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
def test_mms_diffusion_transient_space_converges_at_order_two() -> None:
    """Verify second-order spatial convergence with Crank-Nicolson in time."""
    case_fn = _make_space_case(n_steps_fine=200)
    result = run_mms_convergence(case_fn, refinements=(10, 20, 40, 80))
    errors = np.asarray(result.errors)
    assert np.all(np.diff(errors) < 0.0), (
        f"Spatial MMS errors should decrease, got {errors.tolist()}"
    )
    assert abs(result.order - 2.0) < 0.2, (
        f"Expected second-order spatial convergence, observed slope {result.order:.3f} "
        f"(errors={errors.tolist()})"
    )


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.transient
@pytest.mark.fast
def test_mms_diffusion_transient_time_converges_at_order_one() -> None:
    """Verify first-order temporal convergence under backward Euler."""
    case_fn = _make_time_case(n_cells_fine=200)
    # Step counts chosen so dt stays well above the floor set by spatial error.
    result = run_mms_convergence(case_fn, refinements=(10, 20, 40, 80))
    errors = np.asarray(result.errors)
    assert np.all(np.diff(errors) < 0.0), (
        f"Temporal MMS errors should decrease, got {errors.tolist()}"
    )
    assert abs(result.order - 1.0) < 0.2, (
        f"Expected first-order temporal convergence (backward Euler), "
        f"observed slope {result.order:.3f} (errors={errors.tolist()})"
    )
