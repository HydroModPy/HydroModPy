"""MMS benchmark: 1D Laplacian steady-state with manufactured ``sin(pi x)`` solution.

Manufactured solution on ``[0, 1]`` with Dirichlet 0/0 boundaries::

    u_exact(x) = sin(pi x)
    -u''(x)    = pi^2 sin(pi x) = f(x)

The vertex-centred finite-volume (equivalent to the standard second-order
centred finite-difference) stencil is::

    (u[i-1] - 2 u[i] + u[i+1]) / h^2 = -f[i]

which is second-order consistent. Running on a sequence of refinements and
regressing ``log ||e||_2`` against ``log h`` gives an empirical order
expected to sit inside ``[1.8, 2.2]`` (see ``tests/TOLERANCES.md`` row 8).
"""

from __future__ import annotations

import numpy as np
import pytest

from .conftest import l2_error, run_mms_convergence


def _exact_solution(x: np.ndarray) -> np.ndarray:
    return np.sin(np.pi * x)


def _forcing(x: np.ndarray) -> np.ndarray:
    return (np.pi**2) * np.sin(np.pi * x)


def _solve_laplacian_1d(n_cells: int) -> tuple[np.ndarray, np.ndarray, float]:
    """Return ``(x, u_num, h)`` for the centred FD solution with Dirichlet 0/0.

    The grid uses ``n_cells`` interior unknowns on ``[0, 1]`` with uniform
    spacing ``h = 1 / (n_cells + 1)``. The tridiagonal system is assembled
    and solved with ``numpy.linalg.solve`` - large enough for the expected
    refinements (N up to 80) without becoming ill-conditioned.
    """
    if n_cells < 3:
        raise ValueError("n_cells must be >= 3 to estimate a convergence order")
    h = 1.0 / float(n_cells + 1)
    x_interior = np.linspace(h, 1.0 - h, n_cells)
    main = -2.0 * np.ones(n_cells) / (h * h)
    off = np.ones(n_cells - 1) / (h * h)
    a_mat = np.diag(main) + np.diag(off, 1) + np.diag(off, -1)
    rhs = -_forcing(x_interior)
    u_interior = np.linalg.solve(a_mat, rhs)
    x = np.concatenate(([0.0], x_interior, [1.0]))
    u_num = np.concatenate(([0.0], u_interior, [0.0]))
    return x, u_num, h


def _case(n_cells: int) -> tuple[float, float]:
    x, u_num, h = _solve_laplacian_1d(n_cells)
    err = l2_error(u_num, _exact_solution(x), h=h)
    return h, err


@pytest.mark.validation
@pytest.mark.analytical
@pytest.mark.steady
@pytest.mark.fast
def test_mms_laplacian_1d_converges_at_order_two() -> None:
    """Verify ``||u_h - u||_2 = O(h^2)`` for the centred-FD Laplacian."""
    result = run_mms_convergence(_case, refinements=(10, 20, 40, 80))

    # Errors must decrease monotonically under refinement.
    errors = np.asarray(result.errors)
    assert np.all(np.diff(errors) < 0.0), (
        f"MMS errors should decrease under refinement, got {errors.tolist()}"
    )

    # The empirical order must lie within the theoretical bracket [1.8, 2.2].
    assert abs(result.order - 2.0) < 0.2, (
        f"Expected second-order convergence, observed slope {result.order:.3f} "
        f"(errors={errors.tolist()})"
    )
