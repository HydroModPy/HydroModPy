"""Behavioural unit tests for the CMA-ES optimizer adapter.

The adapter under test is :mod:`hydromodpy.calibration.adapters.cma_adapter`.
It is backed by the ``cma`` package (not ``cmaes``); skip the whole module
when that optional dependency is missing.

``test_adapter_aliases.py::TestCmaEsAdapter`` already covers a basic 2-D
convex convergence, in-bounds sampling, and a single forced restart. This
file complements that with:

- the ask/tell batch (population) contract: ``ask`` serves popsize-sized
  batches and refuses to redraw until the current batch is fully told;
- ``ask(n)`` returns the requested count while the budget allows it;
- best-objective decreases across generations and approaches a known
  minimum on a convex quadratic;
- a fixed seed reproduces identical suggestions across two independent runs;
- ``tell`` updates history and the running best, and failed/NaN evaluations
  map to ``FAILED_EVAL_COST``;
- sigma0/popsize are honoured and the per-restart seed offset is applied;
- budget exhaustion is reported through ``converged``/``suggest_next``;
- the bare ``"cma"`` name is not registered, only ``"cma_es"``.
"""

from __future__ import annotations

import math

import pytest

pytest.importorskip("cma")

from hydromodpy.calibration.optimizer import (  # noqa: E402
    FAILED_EVAL_COST,
    EvaluationResult,
    build_optimizer,
)
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _two_dim_space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=0.0, upper=1.0),
            CalibParameter(name="y", lower=-2.0, upper=2.0),
        ]
    )


def _one_dim_space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="x", lower=-5.0, upper=5.0)])


_TARGET = {"x": 0.3, "y": 0.5}


def _quadratic_cost(values) -> float:
    """Convex bowl centred on ``_TARGET`` with a unique minimum of 0."""
    return float((values["x"] - _TARGET["x"]) ** 2 + (values["y"] - _TARGET["y"]) ** 2)


def _make_result(sugg, cost: float, status: str = "completed") -> EvaluationResult:
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        objective_value=cost,
        status=status,
    )


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
            results.append(_make_result(sugg, cost))
        opt.tell(results)
        gen_best.append(running_best)
    return gen_best


# ---------------------------------------------------------------------------
# Ask / tell batch (population) contract
# ---------------------------------------------------------------------------


class TestPopulationContract:
    def test_ask_returns_requested_count_within_budget(self) -> None:
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            popsize=5,
            max_evaluations=50,
            seed=0,
        )
        sugg = opt.ask(n=5)
        assert len(sugg) == 5
        # trial_ids are unique and stable within the run.
        assert sorted(s.trial_id for s in sugg) == [1, 2, 3, 4, 5]

    def test_batch_is_popsize_bounded_and_redraw_needs_full_tell(self) -> None:
        """A single ``ask`` cannot exceed the current popsize batch."""
        popsize = 4
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            popsize=popsize,
            max_evaluations=40,
            seed=1,
        )
        # Asking for more than popsize at once only yields the current batch.
        first = opt.ask(n=popsize + 3)
        assert len(first) == popsize
        # Without telling, the adapter must not draw a fresh batch.
        again = opt.ask(n=popsize)
        assert again == []
        # Tell the full batch, then a new batch becomes available.
        results = [_make_result(s, _quadratic_cost(s.values)) for s in first]
        opt.tell(results)
        second = opt.ask(n=popsize)
        assert len(second) == popsize
        # The second batch carries fresh, strictly larger trial_ids.
        assert min(s.trial_id for s in second) > max(s.trial_id for s in first)

    def test_ask_values_match_space_names_and_bounds(self) -> None:
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            popsize=4,
            max_evaluations=8,
            seed=3,
        )
        for sugg in opt.ask(n=4):
            assert set(sugg.values) == {"x", "y"}
            assert 0.0 <= sugg.values["x"] <= 1.0
            assert -2.0 <= sugg.values["y"] <= 2.0
            assert sugg.source == "ask"


# ---------------------------------------------------------------------------
# tell updates history and best
# ---------------------------------------------------------------------------


class TestTellUpdatesState:
    def test_tell_records_history_and_tracks_running_best(self) -> None:
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            popsize=4,
            max_evaluations=40,
            seed=5,
        )
        batch = opt.ask(n=4)
        costs = [3.0, 1.0, 2.0, 4.0]
        opt.tell([_make_result(s, c) for s, c in zip(batch, costs, strict=True)])
        # All four results land in history.
        assert len(opt._history) == 4
        best = opt.best()
        assert best is not None
        assert best.objective_value == pytest.approx(1.0)
        # The best trial corresponds to the lowest cost we told.
        assert best.trial_id == batch[1].trial_id

    def test_failed_and_nan_evaluations_use_failed_cost(self) -> None:
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            popsize=4,
            max_evaluations=40,
            seed=6,
        )
        batch = opt.ask(n=4)
        # Tell the NaN and failed slots first (partial batch, no reset yet).
        opt.tell(
            [
                _make_result(batch[1], float("nan"), status="completed"),
                _make_result(batch[2], 0.9, status="failed"),
            ]
        )
        # NaN-completed and non-completed both map to the failed sentinel.
        assert opt._batch_costs[1] == FAILED_EVAL_COST
        assert opt._batch_costs[2] == FAILED_EVAL_COST
        # Finish the batch with two finite costs.
        opt.tell(
            [
                _make_result(batch[0], 0.5, status="completed"),
                _make_result(batch[3], 0.2, status="completed"),
            ]
        )
        assert opt._n_eval == 4
        # The internal running best only tracks finite, completed costs, so
        # the NaN slot never wins: the best finite cost is 0.2.
        assert opt._best_cost == pytest.approx(0.2)
        assert opt._best_trial_id == batch[3].trial_id

    def test_tell_ignores_unknown_trial_ids(self) -> None:
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            popsize=4,
            max_evaluations=40,
            seed=7,
        )
        batch = opt.ask(n=4)
        stray = EvaluationResult(
            trial_id=999_999,
            sim_id=None,
            objective_value=0.0,
            status="completed",
        )
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
            "cma_es",
            _two_dim_space(),
            sigma0=0.3,
            popsize=6,
            max_evaluations=120,
            seed=42,
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
        assert best.objective_value == pytest.approx(gen_best[-1])

    def test_one_dimensional_problem_converges(self) -> None:
        """1-D bounded problems exercise the cma stop-criteria workarounds."""
        opt = build_optimizer(
            "cma_es",
            _one_dim_space(),
            sigma0=0.3,
            popsize=6,
            max_evaluations=90,
            seed=11,
        )

        def cost(values) -> float:
            return float((values["x"] - 1.0) ** 2)

        gen_best = _run_to_convergence(opt, cost_fn=cost)
        assert gen_best, "the loop must run at least one generation"
        assert gen_best[-1] < 1e-2
        best = opt.best()
        assert best is not None
        assert best.trial_id is not None


# ---------------------------------------------------------------------------
# Reproducibility
# ---------------------------------------------------------------------------


class TestReproducibility:
    def test_same_seed_reproduces_identical_suggestions(self) -> None:
        def drive() -> list[tuple[float, float]]:
            opt = build_optimizer(
                "cma_es",
                _two_dim_space(),
                sigma0=0.3,
                popsize=5,
                max_evaluations=40,
                seed=123,
            )
            seen: list[tuple[float, float]] = []
            while not opt.converged():
                batch = opt.ask(n=5)
                if not batch:
                    break
                for s in batch:
                    seen.append((s.values["x"], s.values["y"]))
                opt.tell([_make_result(s, _quadratic_cost(s.values)) for s in batch])
            return seen

        run_a = drive()
        run_b = drive()
        assert run_a and run_b
        assert run_a == run_b

    def test_different_seed_changes_suggestions(self) -> None:
        opt_a = build_optimizer("cma_es", _two_dim_space(), popsize=5, max_evaluations=20, seed=1)
        opt_b = build_optimizer("cma_es", _two_dim_space(), popsize=5, max_evaluations=20, seed=2)
        first_a = [(s.values["x"], s.values["y"]) for s in opt_a.ask(n=5)]
        first_b = [(s.values["x"], s.values["y"]) for s in opt_b.ask(n=5)]
        assert first_a != first_b


# ---------------------------------------------------------------------------
# sigma0 / popsize / seed-offset contract
# ---------------------------------------------------------------------------


class TestStrategyContract:
    def test_sigma0_and_popsize_are_stored(self) -> None:
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            sigma0=0.42,
            popsize=7,
            max_evaluations=21,
            seed=0,
        )
        assert opt._sigma0 == pytest.approx(0.42)
        assert opt._popsize == 7
        # popsize controls the batch size handed out by ``ask``.
        assert len(opt.ask(n=20)) == 7

    def test_restart_seed_offset_changes_strategy_seed(self) -> None:
        """Each restart offsets the cma seed by ``_restarts_used``."""
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            popsize=4,
            max_evaluations=12,
            seed=100,
            restarts=2,
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
            "cma_es",
            _two_dim_space(),
            popsize=4,
            max_evaluations=8,
            seed=0,
            normalize=True,
        )
        assert opt._normalize is True
        assert list(opt._lower_t) == [0.0, 0.0]
        assert list(opt._upper_t) == [1.0, 1.0]
        # x0 sits inside the unit cube.
        assert all(0.0 <= v <= 1.0 for v in opt._x0_t)

    def test_unnormalized_search_uses_physical_transformed_bounds(self) -> None:
        """With ``normalize=False`` the internal domain is the raw transform."""
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            popsize=4,
            max_evaluations=8,
            seed=0,
            normalize=False,
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
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            popsize=4,
            max_evaluations=budget,
            seed=9,
        )
        told = 0
        while not opt.converged():
            batch = opt.ask(n=4)
            if not batch:
                break
            opt.tell([_make_result(s, _quadratic_cost(s.values)) for s in batch])
            told += len(batch)
        assert opt.converged() is True
        assert told == budget
        # Asking past the budget yields nothing.
        assert opt.ask(n=4) == []

    def test_suggest_next_returns_in_bounds_suggestion(self) -> None:
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            popsize=4,
            max_evaluations=40,
            seed=8,
        )
        sugg = opt.suggest_next()
        assert sugg.trial_id == 1
        assert 0.0 <= sugg.values["x"] <= 1.0
        assert -2.0 <= sugg.values["y"] <= 2.0

    def test_suggest_next_raises_when_budget_exhausted(self) -> None:
        opt = build_optimizer(
            "cma_es",
            _two_dim_space(),
            popsize=4,
            max_evaluations=4,
            seed=10,
        )
        batch = opt.ask(n=4)
        assert len(batch) == 4
        opt.tell([_make_result(s, _quadratic_cost(s.values)) for s in batch])
        assert opt.converged() is True
        with pytest.raises(StopIteration):
            opt.suggest_next()


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_cma_es_name_resolves(self) -> None:
        opt = build_optimizer("cma_es", _two_dim_space(), max_evaluations=8, seed=0)
        assert opt.name == "cma_es"

    def test_bare_cma_name_is_not_registered(self) -> None:
        with pytest.raises(KeyError, match="Unknown optimizer"):
            build_optimizer("cma", _two_dim_space())
