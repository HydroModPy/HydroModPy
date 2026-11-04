"""Tests of `optim.adapters.scipy_adapter`."""

from __future__ import annotations

import math

import pytest

from hydromodpy.calibration.optim.adapters.scipy_adapter import ScipyDE, ScipyNelderMead
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import (
    FAILED_EVAL_COST,
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.persistence import PhaseContext, _build_trial
from tests.unit.calibration._factories import two_dim_space
from tests.unit.calibration._factories_search import result_of, run_engine

# From test_a_speculative_trial_is_journaled_as_such.py
# A candidate a parallel simplex solved and did not read is journaled as such.
#
# It is a real solve and stays in the history, but it is not on the path of the
# search: the journal marks it, and the progress bar does not count it.


def _space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="x", lower=-2.0, upper=2.0)])


def _bowl(sugg: ParamSuggestion) -> EvaluationResult:
    x = float(sugg.values["x"])
    return result_of(sugg, (x - 0.7) ** 2)


def test_unused_candidates_are_marked_in_the_journal_and_not_counted() -> None:
    journal: list[bool] = []
    counted: list[int] = []

    class _Reporter:
        def update(self, trial_id, result) -> None:
            counted.append(trial_id)

        def close(self) -> None:
            pass

    def on_iteration(sugg: ParamSuggestion, result: EvaluationResult) -> None:
        journal.append(
            _build_trial(1, PhaseContext(), sugg, result, "summary", "case").speculative_unused
        )

    session = run_engine(
        _space(),
        ScipyNelderMead(_space(), maxiter=12),
        _bowl,
        12,
        parallel=4,
        progress=_Reporter(),
        on_iteration=on_iteration,
    )

    unused = [flag for flag in journal if flag]
    assert unused, "a width of 4 speculates, so some candidates go unread"
    assert len(counted) == len(journal) - len(unused)
    assert len(session.history) == len(journal)


# From test_scipy_adapter.py
# Behavioral unit tests for the SciPy optimizer adapters.
#
# Covers :mod:`hydromodpy.calibration.optim.adapters.scipy_adapter`
# (``scipy_de`` and ``scipy_nelder_mead``), which bridge SciPy's push-style
# ``differential_evolution`` / ``minimize`` API to the ask/tell Protocol via a
# background worker thread and a pair of queues.
#
# Focus:
#
# - ``ask(n>1)`` on the sequential SciPy adapters returns only the points that
#   are already available and never blocks (regression for a deadlock where the
#   worker is blocked waiting for the previous ``tell``);
# - ``close`` is cancel-safe when the loop exits on its budget before the
#   optimizer converges (the worker terminates, no thread is left blocked);
# - DE / Nelder-Mead drive a convex quadratic to its known minimum, seeded
#   reproducibly;
# - ``tell`` of a failed/NaN evaluation maps to ``FAILED_EVAL_COST`` and never
#   poisons the run;
# - only ``scipy_de`` / ``scipy_nelder_mead`` are registered, not ``scipy``.


_TARGET = {"x": 0.3, "y": 0.5}


def _quadratic_cost(values) -> float:
    """Convex bowl centered on ``_TARGET`` with a unique minimum of 0."""
    return float((values["x"] - _TARGET["x"]) ** 2 + (values["y"] - _TARGET["y"]) ** 2)


def _drive(opt, cost_fn=_quadratic_cost, ask_n: int = 1, guard: int = 20000):
    """Drive a full ask/tell loop to convergence. Return the running best costs."""
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
            cost = cost_fn(sugg.values)
            running = min(running, cost)
            results.append(result_of(sugg, cost))
        opt.tell(results)
        best_curve.append(running)
    return best_curve


# ---------------------------------------------------------------------------
# Deadlock regression: batched ask on a sequential adapter
# ---------------------------------------------------------------------------
def test_de_ask_batch_returns_available_without_blocking() -> None:
    opt = ScipyDE(two_dim_space(), seed=0, max_trials=110, popsize=5)
    try:
        # The previous implementation blocked forever here: a sequential DE
        # (workers=1) produces the next point only after the current one is
        # told, so the second blocking ``get`` never returned.
        batch = opt.ask(5)
        assert 1 <= len(batch) <= 5
        # The single ready point is a real, in-bounds suggestion.
        first = batch[0]
        assert set(first.values) == {"x", "y"}
        assert 0.0 <= first.values["x"] <= 1.0
        assert -2.0 <= first.values["y"] <= 2.0
        opt.tell([result_of(s, _quadratic_cost(s.values)) for s in batch])
    finally:
        opt.close()


@pytest.mark.parametrize(("width", "asked"), [(1, 1), (2, 10), (4, 10)])
def test_de_hands_out_a_generation_whole_from_a_width_of_two(width: int, asked: int) -> None:
    # Two parameters and popsize 5 make a generation of 10.
    opt = ScipyDE(two_dim_space(), seed=0, max_trials=110, popsize=5, width=width)
    try:
        batch = opt.ask(100)
        assert [(s.trial_id, s.source) for s in batch] == [(i, "ask") for i in range(1, asked + 1)]
    finally:
        opt.close()


def test_de_asks_one_point_unless_told_otherwise() -> None:
    opt = ScipyDE(two_dim_space(), seed=0, max_trials=110, popsize=5, width=4)
    try:
        assert len(opt.ask()) == 1
    finally:
        opt.close()


@pytest.mark.parametrize(("status", "cost"), [("failed", 5.0), ("completed", math.nan)])
def test_a_result_with_no_usable_cost_is_fed_as_the_failure_cost(status: str, cost: float) -> None:
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


@pytest.mark.parametrize("target", [-5.0, 5.0])
def test_nelder_mead_never_suggests_a_point_outside_the_bounds(target: float) -> None:
    space = ParameterSpace([CalibParameter(name="x", lower=-2.0, upper=2.0)])
    opt = ScipyNelderMead(space, maxiter=30)
    xs: list[float] = []
    for _ in range(30):
        batch = opt.ask(1)
        if not batch:
            break
        xs.append(batch[0].values["x"])
        opt.tell([result_of(batch[0], (xs[-1] - target) ** 2)])
    assert min(xs) >= -2.0 and max(xs) <= 2.0
    assert (min(xs) if target < 0 else max(xs)) == math.copysign(2.0, target)
    assert [(s.trial_id, s.source) for s in ScipyNelderMead(space).ask(2)] == [
        (1, "ask"),
        (2, "ask"),
    ]
    assert len(ScipyNelderMead(space).ask()) == 1


def test_nelder_mead_ask_batch_returns_available_without_blocking() -> None:
    opt = ScipyNelderMead(two_dim_space(), seed=0, maxiter=10)
    try:
        batch = opt.ask(4)
        assert 1 <= len(batch) <= 4
        opt.tell([result_of(s, _quadratic_cost(s.values)) for s in batch])
    finally:
        opt.close()


# ---------------------------------------------------------------------------
# Cancel-safe close
# ---------------------------------------------------------------------------
def test_close_is_cancel_safe_after_early_exit() -> None:
    """Exiting the loop before convergence and closing must not leave a worker
    blocked on the next ``tell``."""
    opt = ScipyDE(two_dim_space(), seed=0, max_trials=3030, popsize=15, tol=1e-9)
    for _ in range(5):
        batch = opt.ask(1)
        assert batch
        opt.tell([result_of(s, _quadratic_cost(s.values)) for s in batch])
    assert not opt.converged()  # budget intentionally not exhausted
    opt.close()
    # The background worker really terminated (no deadlocked thread survives).
    assert not opt._bridge._thread.is_alive()
    # close is idempotent.
    opt.close()


# ---------------------------------------------------------------------------
# The budget sets the generations
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(("max_trials", "evaluations"), [(60, 60), (65, 70), (5, 20)])
def test_de_runs_the_generations_its_budget_covers(max_trials: int, evaluations: int) -> None:
    # Two parameters and popsize 5 give 10 evaluations a generation, the first of
    # them the initial population. A budget of 65 needs 7 of them, and a budget
    # under two generations still runs one after the initial population.
    opt = ScipyDE(two_dim_space(), seed=0, max_trials=max_trials, popsize=5, tol=0.0)
    try:
        assert len(_drive(opt, ask_n=1, cost_fn=_quadratic_cost)) == evaluations
    finally:
        opt.close()


# ---------------------------------------------------------------------------
# Convergence on a convex quadratic
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("width", [1, 4])
def test_de_converges_to_known_minimum(width: int) -> None:
    opt = ScipyDE(two_dim_space(), seed=1, max_trials=1220, popsize=10, tol=1e-7, width=width)
    try:
        curve = _drive(opt, ask_n=4)
        assert curve  # at least one generation ran
        best = opt.best()
        assert best is not None
        assert best.cost < 1e-3
        assert curve[-1] <= curve[0]  # running best never increases
    finally:
        opt.close()


def test_nelder_mead_converges_to_known_minimum() -> None:
    opt = ScipyNelderMead(two_dim_space(), seed=0, maxiter=200)
    try:
        _drive(opt, ask_n=3)
        best = opt.best()
        assert best is not None
        assert best.cost < 1e-4
    finally:
        opt.close()


def test_de_seed_is_reproducible() -> None:
    runs = []
    for _ in range(2):
        opt = ScipyDE(two_dim_space(), seed=7, max_trials=656, popsize=8, tol=1e-7)
        try:
            _drive(opt, ask_n=1)
            runs.append(opt.best().cost)
        finally:
            opt.close()
    assert runs[0] == runs[1]


# ---------------------------------------------------------------------------
# tell semantics
# ---------------------------------------------------------------------------
def test_best_is_none_before_any_completed_eval() -> None:
    opt = ScipyDE(two_dim_space(), seed=0, max_trials=60, popsize=5)
    try:
        assert opt.best() is None
    finally:
        opt.close()


def test_failed_eval_maps_to_failed_cost_and_is_excluded_from_best() -> None:
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
                    # First evaluation fails: must not poison the optimizer.
                    results.append(result_of(sugg, float("nan"), status="failed"))
                    first = False
                else:
                    results.append(result_of(sugg, _quadratic_cost(sugg.values)))
            opt.tell(results)
        best = opt.best()
        # best() only ever returns a completed evaluation, never the failure.
        assert best is not None
        assert best.status == "completed"
        assert best.cost < FAILED_EVAL_COST
    finally:
        opt.close()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def test_registered_names() -> None:
    assert isinstance(build_optimizer("scipy_de", two_dim_space(), seed=0), ScipyDE)
    nm = build_optimizer("scipy_nelder_mead", two_dim_space(), seed=0)
    assert isinstance(nm, ScipyNelderMead)
    build_optimizer("scipy_de", two_dim_space(), seed=0).close()
    nm.close()


def test_a_closed_differential_evolution_says_it_has_finished() -> None:
    adapter = build_optimizer("scipy_de", _space(), seed=1)
    adapter.close()

    assert adapter._bridge.finished()
    while got := adapter.ask(1):
        pass
    assert got == []
    with pytest.raises(StopIteration, match="scipy optimizer finished"):
        adapter.suggest_next()


def test_a_simplex_with_no_call_left_has_nothing_to_suggest() -> None:
    adapter = ScipyNelderMead(_space(), maxfev=1)
    (only,) = adapter.ask(5)
    adapter.tell([_bowl(only)])

    with pytest.raises(StopIteration, match="scipy optimizer finished"):
        adapter.suggest_next()


def test_a_result_naming_no_pending_trial_answers_the_oldest_one() -> None:
    adapter = ScipyNelderMead(_space())
    first, second = adapter.ask(2)

    adapter.tell([EvaluationResult(trial_id=99, sim_id=None, cost=math.nan, status="failed")])
    adapter.tell([_bowl(second)])

    assert adapter._simplex.used[0].value == FAILED_EVAL_COST
    assert first.trial_id == 1


def test_a_result_with_nothing_pending_is_dropped() -> None:
    adapter = ScipyNelderMead(_space(), maxfev=1)
    (only,) = adapter.ask(1)
    adapter.tell([_bowl(only)])

    adapter.tell([EvaluationResult(trial_id=7, sim_id=None, cost=1.0, status="completed")])

    assert len(adapter._simplex.used) == 1


@pytest.mark.parametrize(("popsize", "dim", "size"), [(1, 1, 5), (3, 1, 5), (2, 3, 6)])
def test_a_de_generation_holds_five_points_at_least(popsize: int, dim: int, size: int) -> None:
    from hydromodpy.calibration.optim.adapters.scipy_adapter import _population

    assert _population(popsize, dim) == size


@pytest.mark.parametrize(("width", "parallel"), [(1, False), (2, True)])
def test_de_hands_scipy_its_options_and_deferred_updating_from_a_width_of_two(
    monkeypatch, width: int, parallel: bool
) -> None:
    import scipy.optimize

    seen: dict = {}
    monkeypatch.setattr(
        scipy.optimize, "differential_evolution", lambda *args, **kw: seen.update(kw)
    )
    block = object()
    opt = ScipyDE.__new__(ScipyDE)
    opt.__dict__.update(
        space=two_dim_space(), _seed=0, _max_trials=110, _popsize=5, _tol=0.2, _width=width
    )
    opt._make_method()(lambda x: 0.0, block)

    assert (seen["popsize"], seen["tol"], seen["polish"]) == (5, 0.2, False)
    assert seen["init"].shape == (10, 2)
    assert seen.get("updating") == ("deferred" if parallel else None)
    assert seen.get("workers") is (block if parallel else None)
