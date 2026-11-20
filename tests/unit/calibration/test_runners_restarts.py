"""Repeated searches from other start points: the answer is the best restart, the spread sits beside it.

The solver never runs. Parameters are K (m/s) and Sy (-), searched in log space.
"""

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


def test_one_restart_refused() -> None:
    with pytest.raises(ValueError, match="at least two searches"):
        assert_restarts_can_explore("scipy_nelder_mead", 1)


def test_starts_inside_bounds() -> None:
    for point in start_points(SPACE, restarts=6, seed=7)[1:]:
        assert point.size == SPACE.dim
        for value, (low, high) in zip(point, SPACE.transformed_bounds.values(), strict=True):
            assert low <= value <= high


def test_fixed_search_refused() -> None:
    with pytest.raises(ValueError, match="same answer every time"):
        run_restarts(lambda *_: None, method="grid", space=SPACE, restarts=2, seed=0)


def test_answer_is_best_restart() -> None:
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
def test_answer_is_best_settled(settled, costs, expected_cost, expected_status) -> None:
    def run_one(seed, _start, _index):
        return _report(costs[seed], settled=settled[seed], K=1e-5, Sy=0.01)

    best, _spread = run_restarts(
        run_one, method="scipy_nelder_mead", space=SPACE, restarts=3, seed=0
    )
    assert best.best_cost == pytest.approx(expected_cost)
    assert (best.status, best.extra["search_status"]) == (expected_status,) * 2


def test_failed_restart_out_of_spread() -> None:
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


def test_all_failing_returns_first() -> None:
    best, spread = run_restarts(
        lambda seed, _p, _i: _report(None, settled=seed == 1),
        method="optuna",
        space=SPACE,
        restarts=2,
        seed=0,
    )
    assert best.status == "partial"
    assert spread == ()


def test_restarts_run_side_by_side() -> None:
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


def test_failure_calls_stop_hook() -> None:
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


def test_failure_stops_others() -> None:
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


def test_failure_without_hook_raises() -> None:
    def work(item):
        raise RuntimeError("it failed")

    with pytest.raises(RuntimeError, match="it failed"):
        run_side_by_side(work, [0], width=1)


def test_mixed_sign_spans_a_decade() -> None:
    mixed = RestartSpread(parameter="K", best=0.0, lowest=-1.0, highest=2.0)
    same = RestartSpread(parameter="K", best=0.0, lowest=0.0, highest=0.0)
    assert (mixed.spans_a_decade, same.spans_a_decade) == (True, False)


def test_spread_dict() -> None:
    spread = RestartSpread(parameter="K", best=1e-5, lowest=8e-6, highest=1.4e-5, values=(1.0,) * 5)
    payload = spread.to_dict()
    assert payload["best"] == pytest.approx(1e-5)
    assert payload["n_restarts"] == 5
    assert payload["spans_a_decade"] is False


def test_unscored_parameter_no_spread() -> None:
    reports = [make_report(best_parameters={"K": 2e-5}), make_report(best_parameters={"K": 5e-5})]

    spread = spread_of(reports, best=reports[0], names=["Sy", "K"])

    assert [(item.parameter, item.best, item.lowest, item.highest) for item in spread] == [
        ("K", 2e-5, 2e-5, 5e-5)
    ]


def test_unsettled_search_rule() -> None:
    def search(rule):
        return make_report(extra={"search": {"stop_state": "budget_spent", "stopping_rule": rule}})

    assert unsettled_search(search("xatol")) == {
        "stop_state": "budget_spent",
        "stopping_rule": "xatol",
    }
    assert unsettled_search(search(BUDGET_RULE)) is None
