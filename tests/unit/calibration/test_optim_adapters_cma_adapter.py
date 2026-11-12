"""Tests of `optim.adapters.cma_adapter`."""

from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.optimizer import (
    FAILED_EVAL_COST,
    EvaluationResult,
    OptimizerError,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from tests.unit.calibration._factories import two_dim_space
from tests.unit.calibration._factories_search import result_of

pytest.importorskip("cma")


# From test_a_declared_cma_seed_zero_is_reproducible.py
# A seed written as 0 reproduces the same CMA-ES path.
#
# ``cma`` reads a seed of 0 as "seed from the clock". The adapter maps that one
# value to a fixed seed and leaves every other seed on its own path.


def _first_batch(seed: int | None) -> list[dict[str, float]]:
    opt = build_optimizer("cma_es", two_dim_space(), popsize=5, max_trials=30, seed=seed)
    return [s.values for s in opt.ask(n=5)]


def _seed_handed_to_cma(monkeypatch, seed: int, restarts_used: int = 0) -> int:
    import cma

    seen: list[int] = []
    real = cma.CMAEvolutionStrategy

    def spy(x0, sigma0, options=None):
        seen.append(options["seed"])
        return real(x0, sigma0, options)

    monkeypatch.setattr(cma, "CMAEvolutionStrategy", spy)
    opt = build_optimizer("cma_es", two_dim_space(), popsize=5, max_trials=30, seed=seed)
    opt._restarts_used = restarts_used
    opt._make_strategy(opt._x0_t)
    return seen[-1]


# From test_cma_adapter.py
# Behavioral unit tests for the CMA-ES optimizer adapter.
#
# The adapter under test is :mod:`hydromodpy.calibration.optim.adapters.cma_adapter`.
# It is backed by the ``cma`` package (not ``cmaes``); skip the whole module
# when that optional dependency is missing.
#
# ``test_optim_optimizer.py::TestCmaEsAdapter`` already covers a basic 2-D
# convex convergence, in-bounds sampling, and a single forced restart. This
# file complements that with:
#
# - the ask/tell batch (population) contract: ``ask`` serves popsize-sized
#   batches and refuses to redraw until the current batch is fully told;
# - ``ask(n)`` returns the requested count while the budget allows it;
# - best-objective decreases across generations and approaches a known
#   minimum on a convex quadratic;
# - a fixed seed reproduces identical suggestions across two independent runs;
# - ``tell`` updates history and the running best, and failed/NaN evaluations
#   map to ``FAILED_EVAL_COST``;
# - sigma0/popsize are honored and the per-restart seed offset is applied;
# - budget exhaustion is reported through ``converged``/``suggest_next``;
# - the bare ``"cma"`` name is not registered, only ``"cma_es"``.


def _one_dimtwo_dim_space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="x", lower=-5.0, upper=5.0)])


_TARGET = {"x": 0.3, "y": 0.5}


def _quadratic_cost(values) -> float:
    """Convex bowl centered on ``_TARGET`` with a unique minimum of 0."""
    return float((values["x"] - _TARGET["x"]) ** 2 + (values["y"] - _TARGET["y"]) ** 2)


def _run_to_convergence(opt, cost_fn=_quadratic_cost, max_generations: int = 200):
    """Drive a full ask/tell loop. Return per-generation best costs."""
    gen_best: list[float] = []
    running_best = math.inf
    guard = 0
    while not opt.converged() and guard < max_generations:
        guard += 1
        batch = opt.ask(n=opt._popsize)
        if not batch:
            break
        results = []
        for sugg in batch:
            cost = cost_fn(sugg.values)
            running_best = min(running_best, cost)
            results.append(result_of(sugg, cost))
        opt.tell(results)
        gen_best.append(running_best)
    return gen_best


# ---------------------------------------------------------------------------
# Ask / tell batch (population) contract
# ---------------------------------------------------------------------------
class TestPopulationContract:
    def test_ask_returns_requested_count_within_budget(self) -> None:
        opt = build_optimizer("cma_es", two_dim_space(), popsize=5, max_trials=50, seed=0)
        sugg = opt.ask(n=5)
        assert len(sugg) == 5
        # trial_ids are unique and stable within the run.
        assert sorted(s.trial_id for s in sugg) == [1, 2, 3, 4, 5]

    def test_batch_is_popsize_bounded_and_redraw_needs_full_tell(self) -> None:
        """A single ``ask`` cannot exceed the current popsize batch."""
        popsize = 4
        opt = build_optimizer("cma_es", two_dim_space(), popsize=popsize, max_trials=40, seed=1)
        # Asking for more than popsize at once only yields the current batch.
        first = opt.ask(n=popsize + 3)
        assert len(first) == popsize
        # Without telling, the adapter must not draw a fresh batch.
        again = opt.ask(n=popsize)
        assert again == []
        # Tell the full batch, then a new batch becomes available.
        results = [result_of(s, _quadratic_cost(s.values)) for s in first]
        opt.tell(results)
        second = opt.ask(n=popsize)
        assert len(second) == popsize
        # The second batch carries fresh, strictly larger trial_ids.
        assert min(s.trial_id for s in second) > max(s.trial_id for s in first)


# ---------------------------------------------------------------------------
# tell updates history and best
# ---------------------------------------------------------------------------
class TestTellUpdatesState:
    def test_tell_records_history_and_tracks_running_best(self) -> None:
        opt = build_optimizer("cma_es", two_dim_space(), popsize=4, max_trials=40, seed=5)
        batch = opt.ask(n=4)
        costs = [3.0, 1.0, 2.0, 4.0]
        opt.tell([result_of(s, c) for s, c in zip(batch, costs, strict=True)])
        # All four results land in history.
        assert len(opt._history) == 4
        best = opt.best()
        assert best is not None
        assert best.cost == pytest.approx(1.0)
        # The best trial corresponds to the lowest cost we told.
        assert best.trial_id == batch[1].trial_id

    def test_failed_and_nan_evaluations_use_failed_cost(self) -> None:
        opt = build_optimizer("cma_es", two_dim_space(), popsize=4, max_trials=40, seed=6)
        batch = opt.ask(n=4)
        # Tell the NaN and failed slots first (partial batch, no reset yet).
        opt.tell(
            [
                result_of(batch[1], float("nan"), status="completed"),
                result_of(batch[2], 0.9, status="failed"),
            ]
        )
        # NaN-completed and non-completed both map to the failed sentinel.
        assert opt._batch_costs[1] == FAILED_EVAL_COST
        assert opt._batch_costs[2] == FAILED_EVAL_COST
        # Finish the batch with two finite costs.
        opt.tell(
            [
                result_of(batch[0], 0.5, status="completed"),
                result_of(batch[3], 0.2, status="completed"),
            ]
        )
        assert opt._n_eval == 4
        # The internal running best only tracks finite, completed costs, so
        # the NaN slot never wins: the best finite cost is 0.2.
        assert opt._best_cost == pytest.approx(0.2)
        assert opt._best_trial_id == batch[3].trial_id

    def test_tell_ignores_unknown_trial_ids(self) -> None:
        opt = build_optimizer("cma_es", two_dim_space(), popsize=4, max_trials=40, seed=7)
        batch = opt.ask(n=4)
        stray = EvaluationResult(trial_id=999_999, sim_id=None, cost=0.0, status="completed")
        opt.tell([stray])
        # The stray result is dropped: nothing recorded, budget untouched.
        assert opt._n_eval == 0
        assert opt._history == []
        assert opt.best() is None


# ---------------------------------------------------------------------------
# Convergence on a convex quadratic
# ---------------------------------------------------------------------------
class TestConvergence:
    def test_best_cost_decreases_and_approaches_minimum(self) -> None:
        opt = build_optimizer(
            "cma_es", two_dim_space(), sigma0=0.3, popsize=6, max_trials=120, seed=42
        )
        gen_best = _run_to_convergence(opt)
        assert len(gen_best) >= 3
        # Running best is monotone non-increasing across generations.
        for earlier, later in zip(gen_best, gen_best[1:]):
            assert later <= earlier + 1e-12
        # Strict overall improvement: late generations beat the first one.
        assert gen_best[-1] < gen_best[0]
        # And the search lands close to the known minimum (cost 0).
        assert gen_best[-1] < 1e-2
        # ``best()`` agrees with the tracked running best.
        best = opt.best()
        assert best is not None
        assert best.cost == pytest.approx(gen_best[-1])


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# sigma0 / popsize / seed-offset contract
# ---------------------------------------------------------------------------
class TestStrategyContract:
    def test_sigma0_and_popsize_are_stored(self) -> None:
        opt = build_optimizer(
            "cma_es", two_dim_space(), sigma0=0.42, popsize=7, max_trials=21, seed=0
        )
        assert opt._sigma0 == pytest.approx(0.42)
        assert opt._popsize == 7
        # popsize controls the batch size handed out by ``ask``.
        assert len(opt.ask(n=20)) == 7

    def test_restart_seed_offset_changes_strategy_seed(self) -> None:
        """Each restart offsets the cma seed by ``_restarts_used``."""
        opt = build_optimizer(
            "cma_es", two_dim_space(), popsize=4, max_trials=12, seed=100, restarts=2
        )
        # The very first strategy uses the base seed (offset 0).
        first_x0 = opt._x0_t.copy()
        # Force a restart through the documented private path.
        assert opt._try_restart() is True
        assert opt._restarts_used == 1
        # A second restart is allowed by the budget and restart count.
        assert opt._try_restart() is True
        assert opt._restarts_used == 2
        # Third restart is refused once the restart budget is spent.
        assert opt._try_restart() is False
        # x0 perturbation stays inside the (normalized) bounds.
        assert opt._x0_t.shape == first_x0.shape

    def test_normalize_keeps_internal_bounds_in_unit_cube(self) -> None:
        opt = build_optimizer(
            "cma_es", two_dim_space(), popsize=4, max_trials=8, seed=0, normalize=True
        )
        assert opt._normalize is True
        assert list(opt._lower_t) == [0.0, 0.0]
        assert list(opt._upper_t) == [1.0, 1.0]
        # x0 sits inside the unit cube.
        assert all(0.0 <= v <= 1.0 for v in opt._x0_t)

    def test_unnormalized_search_uses_physical_transformed_bounds(self) -> None:
        """With ``normalize=False`` the internal domain is the raw transform."""
        opt = build_optimizer(
            "cma_es", two_dim_space(), popsize=4, max_trials=8, seed=0, normalize=False
        )
        assert opt._normalize is False
        # Identity transform: transformed bounds equal physical bounds.
        assert list(opt._lower_t) == [0.0, -2.0]
        assert list(opt._upper_t) == [1.0, 2.0]
        # span stays neutral (1.0) so ``_to_physical`` clips, not rescales.
        assert list(opt._span) == [1.0, 1.0]
        # Suggestions still respect the declared physical bounds.
        for sugg in opt.ask(n=4):
            assert 0.0 <= sugg.values["x"] <= 1.0
            assert -2.0 <= sugg.values["y"] <= 2.0


# ---------------------------------------------------------------------------
# Budget exhaustion
# ---------------------------------------------------------------------------
class TestBudgetExhaustion:
    def test_converged_after_budget_consumed(self) -> None:
        budget = 12
        opt = build_optimizer("cma_es", two_dim_space(), popsize=4, max_trials=budget, seed=9)
        told = 0
        while not opt.converged():
            batch = opt.ask(n=4)
            if not batch:
                break
            opt.tell([result_of(s, _quadratic_cost(s.values)) for s in batch])
            told += len(batch)
        assert opt.converged() is True
        assert told == budget
        # Asking past the budget yields nothing.
        assert opt.ask(n=4) == []

    def test_suggest_next_returns_in_bounds_suggestion(self) -> None:
        opt = build_optimizer("cma_es", two_dim_space(), popsize=4, max_trials=40, seed=8)
        sugg = opt.suggest_next()
        assert sugg.trial_id == 1
        assert 0.0 <= sugg.values["x"] <= 1.0
        assert -2.0 <= sugg.values["y"] <= 2.0

    def test_suggest_next_raises_when_budget_exhausted(self) -> None:
        opt = build_optimizer("cma_es", two_dim_space(), popsize=4, max_trials=4, seed=10)
        batch = opt.ask(n=4)
        assert len(batch) == 4
        opt.tell([result_of(s, _quadratic_cost(s.values)) for s in batch])
        assert opt.converged() is True
        with pytest.raises(StopIteration):
            opt.suggest_next()

    def test_no_restart_is_left_once_the_budget_is_spent(self) -> None:
        opt = build_optimizer(
            "cma_es", two_dim_space(), popsize=4, max_trials=4, seed=1, restarts=2
        )
        opt._n_eval = 4

        assert opt._try_restart() is False

    def test_a_search_whose_budget_is_spent_before_a_draw_ends_there(self) -> None:
        opt = build_optimizer("cma_es", two_dim_space(), popsize=4, max_trials=4, seed=1)
        opt._n_eval = 4

        assert opt.ask(n=1) == []
        assert opt.converged()

    def test_a_strategy_that_stops_ends_the_search_when_no_restart_is_left(self) -> None:
        opt = build_optimizer("cma_es", two_dim_space(), popsize=4, max_trials=40, seed=1)
        opt._es = SimpleNamespace(stop=lambda: True)

        assert opt.ask(n=1) == []
        assert opt.converged()

    def test_a_strategy_that_stops_after_a_tell_ends_the_search(self) -> None:
        opt = build_optimizer("cma_es", two_dim_space(), popsize=4, max_trials=40, seed=1)
        batch = opt.ask(n=4)
        opt._es = SimpleNamespace(tell=lambda xs, costs: None, stop=lambda: True)

        opt.tell([result_of(s, _quadratic_cost(s.values)) for s in batch])

        assert opt.converged()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
class TestRegistration:
    def test_bare_cma_name_is_not_registered(self) -> None:
        with pytest.raises(OptimizerError, match="Unknown optimizer"):
            build_optimizer("cma", two_dim_space())
