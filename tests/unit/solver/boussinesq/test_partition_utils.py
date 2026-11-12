"""A failed solve restarts from a smoother surface closure, back to the depth asked.

Where the water table reaches the ground over a wide area, the kink of the release
at the land surface stops Newton. Only the last rung, at the depth the run asks for,
can be the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.solver.boussinesq.runtimes.partition_utils import (
    solve_by_release_depth_continuation,
)

pytestmark = pytest.mark.fast


@dataclass(frozen=True)
class _Options:
    regularization_radius: float = 0.05


@dataclass(frozen=True)
class _Inputs:
    options: _Options = _Options()
    head_initial_guess_m: np.ndarray = field(default_factory=lambda: np.zeros(1))


def _result(converged: bool, head: float, depth: float) -> SimpleNamespace:
    return SimpleNamespace(converged=converged, head_m=np.array([head]), depth=depth)


DIRECT = _result(False, -1.0, 0.05)


def test_rungs_chain_their_heads() -> None:
    calls: list[tuple[float, float]] = []

    def solve(inputs: _Inputs) -> SimpleNamespace:
        calls.append((inputs.options.regularization_radius, float(inputs.head_initial_guess_m[0])))
        return _result(True, float(len(calls)), inputs.options.regularization_radius)

    answer = solve_by_release_depth_continuation(_Inputs(), direct=DIRECT, solve=solve)

    assert [depth for depth, _ in calls] == pytest.approx([0.8, 0.4, 0.2, 0.1, 0.05])
    assert [guess for _, guess in calls] == [0.0, 1.0, 2.0, 3.0, 4.0]
    assert answer.depth == pytest.approx(0.05)


def test_failed_rung_is_skipped() -> None:
    guesses: list[float] = []

    def solve(inputs: _Inputs) -> SimpleNamespace:
        guesses.append(float(inputs.head_initial_guess_m[0]))
        return _result(len(guesses) != 1, float(len(guesses)), 0.05)

    answer = solve_by_release_depth_continuation(_Inputs(), direct=DIRECT, solve=solve)

    assert guesses[:3] == [0.0, 0.0, 2.0]
    assert answer.converged


def test_failure_at_the_depth_asked() -> None:
    def solve(inputs: _Inputs) -> SimpleNamespace:
        at_the_end = inputs.options.regularization_radius == pytest.approx(0.05)
        return _result(not at_the_end, 0.0, inputs.options.regularization_radius)

    answer = solve_by_release_depth_continuation(_Inputs(), direct=DIRECT, solve=solve)

    assert answer is DIRECT
