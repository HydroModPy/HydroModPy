"""Tests of `runners.restarts`."""

from __future__ import annotations

import threading

import pytest

from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import BUDGET_RULE
from hydromodpy.calibration.runners.restarts import (
    RestartSpread,
    assert_restarts_can_explore,
    run_restarts,
    run_side_by_side,
    spread_of,
    start_points,
    unsettled_search,
)
from tests.unit.calibration._factories_runners import make_report

# From test_restarts_report_a_spread_not_a_new_answer.py
# Repeating a search says how far apart its answers land, and changes none of them.
#
# ``cost_profile`` reads one search's own trace, so it reports what that search could
# not tell apart and never what it never visited. Restarting from elsewhere can see a
# second basin. The constraint this obeys is the project's own: the calibrated value
# stays one manipulable number, the best of the restarts, and the spread sits beside
# it.
#
# The solver never runs here. What is gated is the arithmetic and the refusals: how
# many searches happen, that the first one is the single search it replaces, which
# engines may be restarted at all, and that a failed restart is left out of the
# spread rather than counted as an optimum at zero.


K = CalibParameter(name="K", lower=1e-8, upper=1e-2, search_space="log")
SY = CalibParameter(name="Sy", lower=1e-4, upper=0.5, search_space="log")
SPACE = ParameterSpace([K, SY])


def _report(objective, *, settled=True, **values):
    state, status = ("rule_met", "completed") if settled else ("budget_spent", "partial")
    search = {"stop_state": state, "stopping_rule": "xatol"}
    return make_report(
        best_cost=objective,
        best_parameters=values or None,
        status=status,
        extra={"search": search, "search_status": status},
    )


class TestTheRefusals:
    def test_one_restart_is_not_a_spread(self) -> None:
        with pytest.raises(ValueError, match="at least two searches"):
            assert_restarts_can_explore("scipy_nelder_mead", 1)


class TestTheStartPoints:
    def test_every_other_start_is_inside_the_declared_bounds(self) -> None:
        for point in start_points(SPACE, restarts=6, seed=7)[1:]:
            assert point.size == SPACE.dim
            for value, (low, high) in zip(point, SPACE.transformed_bounds.values(), strict=True):
                assert low <= value <= high


class TestTheLoop:
    def test_a_search_that_cannot_explore_is_refused_before_any_run(self) -> None:
        with pytest.raises(ValueError, match="same answer every time"):
            run_restarts(lambda *_: None, method="grid", space=SPACE, restarts=2, seed=0)

    def test_the_answer_is_the_best_restart_and_nothing_new(self) -> None:
        costs = [0.9, 0.3, 0.7]
        values = [1e-5, 4e-6, 2e-5]

        def run_one(seed, _start, _index):
            index = seed - 1
            return _report(costs[index], K=values[index], Sy=0.01)

        best, spread = run_restarts(
            run_one, method="scipy_nelder_mead", space=SPACE, restarts=3, seed=1
        )
        assert best.best_cost == pytest.approx(0.3)
        assert best.best_parameters["K"] == pytest.approx(4e-6)
        k_spread = next(item for item in spread if item.parameter == "K")
        assert k_spread.best == pytest.approx(4e-6)
        assert (k_spread.lowest, k_spread.highest) == (pytest.approx(4e-6), pytest.approx(2e-5))

    @pytest.mark.parametrize(
        ("settled", "costs", "expected_cost", "expected_status"),
        [
            ((False, True, True), (0.3, 0.9, 0.7), 0.7, "completed"),
            ((False, False, False), (0.3, 0.9, 0.7), 0.3, "partial"),
            ((True, True, True), (0.5, None, 0.8), 0.5, "partial"),
        ],
        ids=["the best that settled", "none settled, the best of all", "one found nothing"],
    )
    def test_the_answer_is_the_best_restart_that_settled(
        self, settled, costs, expected_cost, expected_status
    ) -> None:
        def run_one(seed, _start, _index):
            return _report(costs[seed], settled=settled[seed], K=1e-5, Sy=0.01)

        best, _spread = run_restarts(
            run_one, method="scipy_nelder_mead", space=SPACE, restarts=3, seed=0
        )
        assert best.best_cost == pytest.approx(expected_cost)
        assert (best.status, best.extra["search_status"]) == (expected_status,) * 2

    def test_a_restart_that_found_nothing_is_left_out_of_the_spread(self) -> None:
        # A search that failed did not find a different optimum; it found none.
        def run_one(seed, _start, _index):
            if seed == 1:
                return _report(None)
            return _report(0.5, K=1e-5, Sy=0.01)

        _best, spread = run_restarts(
            run_one, method="scipy_nelder_mead", space=SPACE, restarts=3, seed=0
        )
        k_spread = next(item for item in spread if item.parameter == "K")
        assert k_spread.values == (pytest.approx(1e-5), pytest.approx(1e-5))

    def test_every_restart_failing_still_returns_the_first_report(self) -> None:
        best, spread = run_restarts(
            lambda seed, _p, _i: _report(None, settled=seed == 1),
            method="optuna",
            space=SPACE,
            restarts=2,
            seed=0,
        )
        assert best.status == "partial"
        assert spread == ()


class TestSideBySide:
    def test_restarts_wait_for_each_other_at_a_width_of_two_and_keep_their_order(self) -> None:
        # Two restarts that meet at a barrier cannot have run one after the other.
        meeting = threading.Barrier(2, timeout=2.0)
        seen: list[tuple[int, int]] = []

        def run_one(seed, _start, index):
            meeting.wait()
            seen.append((seed, index))
            return _report(1.0 + index, K=1e-5, Sy=0.01)

        best, _spread = run_restarts(
            run_one, method="scipy_nelder_mead", space=SPACE, restarts=2, seed=100, width=2
        )
        assert sorted(seen) == [(100, 0), (101, 1)]
        assert best.best_cost == pytest.approx(1.0)

    def test_a_failure_of_a_restart_calls_the_stop_hook(self) -> None:
        stopped = []

        def run_one(seed, _start, _index):
            if seed == 0:
                raise RuntimeError("it failed")
            return _report(1.0, K=1e-5, Sy=0.01)

        with pytest.raises(RuntimeError, match="it failed"):
            run_restarts(
                run_one,
                method="scipy_nelder_mead",
                space=SPACE,
                restarts=2,
                seed=0,
                width=2,
                on_stop=lambda: stopped.append(True),
            )
        assert stopped == [True]

    def test_a_failure_stops_the_others(self) -> None:
        stopped = threading.Event()

        def work(item):
            if item == 0:
                raise RuntimeError("it failed")
            # Only the stop can end this one, as it ends the solve of a pool.
            assert stopped.wait(timeout=2.0)
            return item

        with pytest.raises(RuntimeError, match="it failed"):
            run_side_by_side(work, [0, 1], width=2, on_stop=stopped.set)
        assert stopped.is_set()

    def test_a_failure_without_a_stop_hook_still_raises(self) -> None:
        def work(item):
            raise RuntimeError("it failed")

        with pytest.raises(RuntimeError, match="it failed"):
            run_side_by_side(work, [0], width=1)


class TestWhatTheSpreadSays:
    def test_optima_of_mixed_sign_are_flagged_unless_equal(self) -> None:
        mixed = RestartSpread(parameter="K", best=0.0, lowest=-1.0, highest=2.0)
        same = RestartSpread(parameter="K", best=0.0, lowest=0.0, highest=0.0)
        assert (mixed.spans_a_decade, same.spans_a_decade) == (True, False)

    def test_the_dict_keeps_the_value_and_the_count(self) -> None:
        spread = RestartSpread(
            parameter="K", best=1e-5, lowest=8e-6, highest=1.4e-5, values=(1.0,) * 5
        )
        payload = spread.to_dict()
        assert payload["best"] == pytest.approx(1e-5)
        assert payload["n_restarts"] == 5
        assert payload["spans_a_decade"] is False


def test_a_parameter_no_restart_scored_has_no_spread() -> None:
    reports = [make_report(best_parameters={"K": 2e-5}), make_report(best_parameters={"K": 5e-5})]

    spread = spread_of(reports, best=reports[0], names=["Sy", "K"])

    assert [(item.parameter, item.best, item.lowest, item.highest) for item in spread] == [
        ("K", 2e-5, 2e-5, 5e-5)
    ]


def test_a_search_that_spent_its_budget_settles_only_under_the_budget_rule() -> None:
    def search(rule):
        return make_report(extra={"search": {"stop_state": "budget_spent", "stopping_rule": rule}})

    assert unsettled_search(search("xatol")) == {
        "stop_state": "budget_spent",
        "stopping_rule": "xatol",
    }
    assert unsettled_search(search(BUDGET_RULE)) is None
