"""Repeating a search says how far apart its answers land, and changes none of them.

``cost_profile`` reads one search's own trace, so it reports what that search could
not tell apart and never what it never visited. Restarting from elsewhere can see a
second basin. The constraint this obeys is the project's own: the calibrated value
stays one manipulable number, the best of the restarts, and the spread sits beside
it.

The solver never runs here. What is gated is the arithmetic and the refusals: how
many searches happen, that the first one is the single search it replaces, which
engines may be restarted at all, and that a failed restart is left out of the
spread rather than counted as an optimum at zero.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest

from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.runners.restarts import (
    RestartSpread,
    assert_restarts_can_explore,
    run_restarts,
    start_points,
)

K = CalibParameter(name="K", lower=1e-8, upper=1e-2, transform="log")
SY = CalibParameter(name="Sy", lower=1e-4, upper=0.5, transform="log")
SPACE = ParameterSpace([K, SY])


def _report(objective, **values):
    return SimpleNamespace(best_objective=objective, best_parameters=values or None)


class TestTheRefusals:
    def test_an_exhaustive_sweep_may_not_be_restarted(self) -> None:
        with pytest.raises(ValueError, match="same answer every time"):
            assert_restarts_can_explore("grid", 8)

    def test_a_root_search_may_not_be_restarted(self) -> None:
        with pytest.raises(ValueError, match="same answer every time"):
            assert_restarts_can_explore("bisection", 8)

    def test_a_simplex_may(self) -> None:
        assert_restarts_can_explore("scipy_nelder_mead", 8)

    def test_one_restart_is_not_a_spread(self) -> None:
        with pytest.raises(ValueError, match="at least two searches"):
            assert_restarts_can_explore("scipy_nelder_mead", 1)


class TestTheStartPoints:
    def test_the_first_restart_is_the_single_search_it_replaces(self) -> None:
        # The engine keeps its own start, so the answer a file already published
        # stays in the set and the others are added around it.
        points = start_points(SPACE, restarts=4, seed=42)
        assert points[0] is None
        assert len(points) == 4

    def test_every_other_start_is_inside_the_declared_bounds(self) -> None:
        for point in start_points(SPACE, restarts=6, seed=7)[1:]:
            assert point.size == SPACE.dim
            for value, (low, high) in zip(point, SPACE.transformed_bounds.values(), strict=True):
                assert low <= value <= high

    def test_the_same_seed_draws_the_same_starts(self) -> None:
        first = start_points(SPACE, restarts=5, seed=11)[1:]
        again = start_points(SPACE, restarts=5, seed=11)[1:]
        assert all(np.array_equal(a, b) for a, b in zip(first, again, strict=True))


class TestTheLoop:
    def test_every_restart_runs_once_with_its_own_seed(self) -> None:
        seen: list[int] = []

        def run_one(seed, _start):
            seen.append(seed)
            return _report(1.0, K=1e-5, Sy=0.01)

        run_restarts(run_one, method="scipy_nelder_mead", space=SPACE, restarts=4, seed=100)
        assert seen == [100, 101, 102, 103]

    def test_the_answer_is_the_best_restart_and_nothing_new(self) -> None:
        costs = [0.9, 0.3, 0.7]
        values = [1e-5, 4e-6, 2e-5]

        def run_one(seed, _start):
            index = seed - 1
            return _report(costs[index], K=values[index], Sy=0.01)

        best, spread = run_restarts(
            run_one, method="scipy_nelder_mead", space=SPACE, restarts=3, seed=1
        )
        assert best.best_objective == pytest.approx(0.3)
        assert best.best_parameters["K"] == pytest.approx(4e-6)
        k_spread = next(item for item in spread if item.parameter == "K")
        assert k_spread.best == pytest.approx(4e-6)
        assert (k_spread.lowest, k_spread.highest) == (pytest.approx(4e-6), pytest.approx(2e-5))

    def test_a_restart_that_found_nothing_is_left_out_of_the_spread(self) -> None:
        # A search that failed did not find a different optimum; it found none.
        def run_one(seed, _start):
            if seed == 1:
                return _report(None)
            return _report(0.5, K=1e-5, Sy=0.01)

        _best, spread = run_restarts(
            run_one, method="scipy_nelder_mead", space=SPACE, restarts=3, seed=0
        )
        k_spread = next(item for item in spread if item.parameter == "K")
        assert k_spread.values == (pytest.approx(1e-5), pytest.approx(1e-5))

    def test_every_restart_failing_still_returns_a_report(self) -> None:
        best, spread = run_restarts(
            lambda _s, _p: _report(None), method="optuna", space=SPACE, restarts=2, seed=0
        )
        assert best is not None
        assert spread == ()


class TestWhatTheSpreadSays:
    def test_optima_a_factor_twenty_apart_are_flagged(self) -> None:
        spread = RestartSpread(parameter="K", best=1e-5, lowest=1e-6, highest=2e-5)
        assert spread.spans_a_decade is True

    def test_optima_within_a_factor_two_are_not(self) -> None:
        spread = RestartSpread(parameter="K", best=1e-5, lowest=8e-6, highest=1.4e-5)
        assert spread.spans_a_decade is False

    def test_the_dict_keeps_the_value_and_the_count(self) -> None:
        spread = RestartSpread(
            parameter="K", best=1e-5, lowest=8e-6, highest=1.4e-5, values=(1.0,) * 5
        )
        payload = spread.to_dict()
        assert payload["best"] == pytest.approx(1e-5)
        assert payload["n_restarts"] == 5
        assert payload["spans_a_decade"] is False
