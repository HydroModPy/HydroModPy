"""The line search of the sparse Boussinesq Newton follows the L2 norm of the residual.

A Newton step lowers the L2 norm, not always the largest entry. On a kink of the
surface closure, one cell holds the maximum while the others fall, and a search on
the maximum rejected every step: the same island passed at 1 mm/day and failed at
1.5, and passed in ``nearest`` and failed in ``area``. The dense runtime keeps the
search on the largest entry, under which its 1D seepage cases converge.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.runtimes import newton_common
from hydromodpy.solver.boussinesq.runtimes.newton_common import _newton_loop_template

pytestmark = pytest.mark.fast


def _assembly(residual: np.ndarray) -> SimpleNamespace:
    return SimpleNamespace(solver_residual=residual)


def _solve(assembly_for) -> object:
    return _newton_loop_template(
        assembly_for=assembly_for,
        head_initial_guess_m=np.zeros(1),
        max_iterations=5,
        tol_residual_inf=1e-9,
        min_damping=1e-4,
        backend_name="test",
        newton_label="test",
        build_jacobian=lambda *args: None,
        solve_linear_system=lambda *args: np.ones(1),
        line_search_norm=lambda residual: float(np.linalg.norm(residual)),
    )


@pytest.fixture(autouse=True)
def _plain_result(monkeypatch) -> None:
    monkeypatch.setattr(newton_common, "build_runtime_result", lambda **kw: SimpleNamespace(**kw))


def test_a_step_that_keeps_the_maximum_and_lowers_the_rest_is_taken() -> None:
    residuals = [
        np.array([1.0, 1.0, 1.0]),
        np.array([1.0, 0.0, 0.0]),
        np.array([0.0, 0.0, 0.0]),
    ]

    result = _solve(lambda head: _assembly(residuals[int(round(head[0]))]))

    assert result.converged
    assert result.iterations == 2


def test_a_step_that_raises_the_l2_norm_is_damped() -> None:
    seen: list[float] = []

    def assembly_for(head: np.ndarray) -> SimpleNamespace:
        seen.append(float(head[0]))
        if head[0] == 0.0:
            return _assembly(np.array([1.0, 0.0]))
        if head[0] == 1.0:
            return _assembly(np.array([0.9, 0.9]))
        return _assembly(np.zeros(2))

    result = _solve(assembly_for)

    assert seen[:3] == [0.0, 1.0, 0.5]
    assert result.converged
