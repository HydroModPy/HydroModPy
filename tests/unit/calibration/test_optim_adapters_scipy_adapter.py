"""SciPy adapters (`optim.adapters.scipy_adapter`), differential evolution and Nelder-Mead.
They bridge SciPy's push-style API to ask/tell through a worker thread.
Costs are dimensionless.
"""

from __future__ import annotations

import math

import pytest

from hydromodpy.calibration.optim.adapters.scipy_adapter import ScipyDE, ScipyNelderMead
from hydromodpy.calibration.optim.optimizer import (
    FAILED_EVAL_COST,
    EvaluationResult,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from tests.unit.calibration._factories import two_dim_space
from tests.unit.calibration._factories_search import result_of

TARGET = {"x": 0.3, "y": 0.5}
UNUSABLE_COSTS = [
    pytest.param("failed", 5.0, id="failed"),
    pytest.param("completed", math.nan, id="nan cost"),
]


def line_space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="x", lower=-2.0, upper=2.0)])


def bowl_cost(values) -> float:
    # Convex bowl with its minimum of 0 at TARGET.
    return float((values["x"] - TARGET["x"]) ** 2 + (values["y"] - TARGET["y"]) ** 2)


def line_bowl(sugg):
    return result_of(sugg, (float(sugg.values["x"]) - 0.7) ** 2)


def drive(opt, ask_n: int = 1, guard: int = 20000) -> list[float]:
    """Run ask/tell to convergence and return the running best cost."""
    best_curve: list[float] = []
    running = math.inf
    loops = 0
    while not opt.converged() and loops < guard:
        loops += 1
        batch = opt.ask(ask_n)
        if not batch:
            break
        results = []
        for sugg in batch:
            cost = bowl_cost(sugg.values)
            running = min(running, cost)
            results.append(result_of(sugg, cost))
        opt.tell(results)
        best_curve.append(running)
    return best_curve


@pytest.mark.parametrize(("width", "asked"), [(1, 1), (2, 10), (4, 10)])
def test_de_generation_size(width, asked):
    # Two parameters and popsize 5 make a generation of 10.
    opt = ScipyDE(two_dim_space(), seed=0, max_trials=110, popsize=5, width=width)
    try:
        batch = opt.ask(100)
        assert [(s.trial_id, s.source) for s in batch] == [(i, "ask") for i in range(1, asked + 1)]
    finally:
        opt.close()


@pytest.mark.parametrize(("status", "cost"), UNUSABLE_COSTS)
def test_de_unusable_cost_is_failure_cost(status, cost):
    opt = ScipyDE(two_dim_space(), seed=0, max_trials=110, popsize=5, width=4)
    fed: list[float] = []
    opt._bridge.feed = fed.append
    try:
        batch = opt.ask(4)
        opt.tell([result_of(batch[1], cost, status=status), result_of(batch[2], 1.0)])
        # Each result takes its own pending point out.
        assert fed == [FAILED_EVAL_COST, 1.0]
        assert [tid for tid, _ in opt._pending] == [1, 4]
    finally:
        opt.close()


def test_close_after_early_exit():
    opt = ScipyDE(two_dim_space(), seed=0, max_trials=3030, popsize=15, tol=1e-9)
    for _ in range(5):
        batch = opt.ask(1)
        assert batch
        opt.tell([result_of(s, bowl_cost(s.values)) for s in batch])
    assert not opt.converged()
    opt.close()
    assert not opt._bridge._thread.is_alive()
    opt.close()  # a second close does nothing


@pytest.mark.parametrize(("max_trials", "evaluations"), [(60, 60), (65, 70), (5, 20)])
def test_de_budget_in_generations(max_trials, evaluations):
    # Two parameters and popsize 5 give 10 evaluations a generation, the first of
    # them the initial population. A budget of 65 needs 7 of them, and a budget
    # under two generations still runs one after the initial population.
    opt = ScipyDE(two_dim_space(), seed=0, max_trials=max_trials, popsize=5, tol=0.0)
    try:
        assert len(drive(opt)) == evaluations
    finally:
        opt.close()


def test_nelder_mead_finds_minimum():
    opt = ScipyNelderMead(two_dim_space(), seed=0, maxiter=200)
    try:
        drive(opt, ask_n=3)
        assert opt.best().cost < 1e-4
    finally:
        opt.close()


def test_de_seed_reproducible():
    costs = []
    for _ in range(2):
        opt = ScipyDE(two_dim_space(), seed=7, max_trials=656, popsize=8, tol=1e-7)
        try:
            drive(opt)
            costs.append(opt.best().cost)
        finally:
            opt.close()
    assert costs[0] == costs[1]


def test_de_best_skips_failed_trial():
    opt = ScipyDE(two_dim_space(), seed=0, max_trials=252, popsize=6, tol=1e-9)
    try:
        first = True
        for _ in range(12):
            batch = opt.ask(1)
            if not batch:
                break
            results = []
            for sugg in batch:
                if first:
                    results.append(result_of(sugg, float("nan"), status="failed"))
                    first = False
                else:
                    results.append(result_of(sugg, bowl_cost(sugg.values)))
            opt.tell(results)
        best = opt.best()
        assert best.status == "completed"
        assert best.cost < FAILED_EVAL_COST
    finally:
        opt.close()


def test_closed_de_is_finished():
    adapter = build_optimizer("scipy_de", line_space(), seed=1)
    adapter.close()

    assert adapter._bridge.finished()
    while got := adapter.ask(1):
        pass
    assert got == []
    with pytest.raises(StopIteration, match="scipy optimizer finished"):
        adapter.suggest_next()


def test_simplex_without_call_left():
    adapter = ScipyNelderMead(line_space(), maxfev=1)
    (only,) = adapter.ask(5)
    adapter.tell([line_bowl(only)])

    with pytest.raises(StopIteration, match="scipy optimizer finished"):
        adapter.suggest_next()


def test_unknown_trial_answers_oldest():
    adapter = ScipyNelderMead(line_space())
    first, second = adapter.ask(2)

    adapter.tell([EvaluationResult(trial_id=99, sim_id=None, cost=math.nan, status="failed")])
    adapter.tell([line_bowl(second)])

    assert adapter._simplex.used[0].value == FAILED_EVAL_COST
    assert first.trial_id == 1


@pytest.mark.parametrize(("status", "cost"), UNUSABLE_COSTS)
def test_simplex_unusable_cost_is_failure_cost(status, cost):
    adapter = ScipyNelderMead(line_space())
    (first, *_) = adapter.ask(2)

    adapter.tell([EvaluationResult(trial_id=first.trial_id, sim_id=None, cost=cost, status=status)])

    assert adapter._simplex.used[0].value == FAILED_EVAL_COST


def test_result_with_nothing_pending_dropped():
    adapter = ScipyNelderMead(line_space(), maxfev=1)
    (only,) = adapter.ask(1)
    adapter.tell([line_bowl(only)])

    adapter.tell([EvaluationResult(trial_id=7, sim_id=None, cost=1.0, status="completed")])

    assert len(adapter._simplex.used) == 1
