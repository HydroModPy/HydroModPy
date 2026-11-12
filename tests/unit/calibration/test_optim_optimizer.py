"""Tests of `optim.optimizer`."""

from __future__ import annotations

import threading
import time
import warnings
from collections.abc import Mapping
from types import SimpleNamespace

import numpy as np
import pytest
import sklearn  # noqa: F401

from hydromodpy.calibration.optim import optimizer as optimizer_module
from hydromodpy.calibration.optim.adapters import optuna_adapter
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.method_config import OptunaMethodConfig
from hydromodpy.calibration.optim.optimizer import (
    EngineTraits,
    EvaluationResult,
    OptimizerError,
    ParamSuggestion,
    build_optimizer,
    choose_method,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from tests.unit.calibration._factories import two_dim_space, unit_space
from tests.unit.calibration._factories_search import make_space, result_of, run_engine

# From test_a_confidence_bound_search_does_not_stop_on_positive_costs.py
# A gp_mapping search on a lower confidence bound judges the bound, not an EI.
#
# With ``kappa != 0`` the acquisition is the negated lower confidence bound.
# For positive costs that score is negative, so reading it as an expected
# improvement made the search "converge" after ``ei_patience`` proposals.


def _space() -> ParameterSpace:
    return make_space(("x", -2.0, 2.0), ("y", -2.0, 2.0))


def _cost(values: dict) -> float:
    return 10.0 + float(values["x"]) ** 2 + float(values["y"]) ** 2


def _tell(opt, sugg) -> None:
    opt.tell([result_of(sugg, _cost(sugg.values))])


def test_a_confidence_bound_search_stops_once_the_bound_promises_nothing():
    opt = build_optimizer(
        "gp_mapping", _space(), seed=11, n_init=4, max_trials=60, kappa=1.5, ei_tol=1e6
    )
    for _ in range(60):
        got = opt.ask(1)
        if not got:
            break
        _tell(opt, got[0])
        if opt.converged():
            break
    assert opt.converged()
    assert len(opt._x_history) < 60


def test_the_confidence_bound_score_is_the_improvement_it_promises():
    opt = build_optimizer("gp_mapping", _space(), seed=11, n_init=4, max_trials=20, kappa=1.5)
    for _ in range(5):
        (sugg,) = opt.ask(1)
        _tell(opt, sugg)
    (sugg,) = opt.ask(1)
    assert opt._last_ei >= 0.0


# From test_a_simplex_runs_on_the_session_budget.py
# A Nelder-Mead search with no maxiter of its own spends the session budget.
#
# The adapter used to cap itself at 100 iterations whatever ``max_trials`` said, so
# a budget of 250 stopped at 100 with the simplex reporting it had run dry.


def _space__simplex_runs() -> ParameterSpace:
    return make_space(("x", -1.0, 1.0), ("y", -1.0, 1.0))


def _noise():
    """A cost no simplex can settle on, so only the budget stops the search."""
    rng = np.random.default_rng(5)

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        return result_of(sugg, float(rng.uniform(1.0, 2.0)))

    return evaluate


def _run(max_trials: int, **options):
    optimizer = build_optimizer(
        "scipy_nelder_mead", _space__simplex_runs(), seed=1, xatol=0.0, fatol=0.0, **options
    )
    return run_engine(optimizer.space, optimizer, _noise(), max_trials)


def test_a_budget_above_one_hundred_is_spent_whole() -> None:
    session = _run(250)

    assert len(session.history) == 250
    assert not session.converged


def test_a_maxiter_written_in_the_file_still_stops_the_simplex() -> None:
    session = _run(250, maxiter=20)

    assert len(session.history) < 250


# From test_adapter_aliases.py
# Tests for canonical optimizer adapter construction.


class TestLegacyAdapterInputsRejected:
    @pytest.mark.parametrize("name", ["simplex", "nelder_mead"])
    def test_removed_nelder_mead_names_are_rejected(self, name: str) -> None:
        with pytest.raises(OptimizerError, match="Unknown optimizer"):
            build_optimizer(name, two_dim_space())


class TestGridAdapter:
    def test_points_per_dim_controls_grid_size(self) -> None:
        opt = build_optimizer("grid", two_dim_space(), points_per_dim=3)
        suggestions = opt.ask(n=9)
        values_x = [s.values["x"] for s in suggestions]
        values_y = [s.values["y"] for s in suggestions]
        assert len(suggestions) == 9
        assert min(values_x) == pytest.approx(0.0)
        assert max(values_x) == pytest.approx(1.0)
        assert min(values_y) == pytest.approx(-2.0)
        assert max(values_y) == pytest.approx(2.0)


class TestRandomSearchSeeding:
    def test_same_seed_yields_same_suggestions(self) -> None:
        opt_a = build_optimizer("random_search", two_dim_space(), seed=7)
        opt_b = build_optimizer("random_search", two_dim_space(), seed=7)
        sugg_a = opt_a.ask(n=4)
        sugg_b = opt_b.ask(n=4)
        for a, b in zip(sugg_a, sugg_b, strict=True):
            assert a.values["x"] == pytest.approx(b.values["x"])
            assert a.values["y"] == pytest.approx(b.values["y"])


class TestCmaEsAdapter:
    def test_cma_adapter_restarts(self) -> None:
        """A restart must re-instantiate the strategy when CMA stops early."""
        pytest.importorskip("cma")
        space = two_dim_space()
        opt = build_optimizer(
            "cma_es", space, sigma0=0.25, popsize=4, max_trials=12, seed=2, restarts=1
        )
        first_es_id = id(opt._es)
        original_stop = opt._es.stop
        forced_stops = {"count": 0}

        def _fake_stop():
            if forced_stops["count"] < 1:
                forced_stops["count"] += 1
                return {"forced": True}
            return original_stop()

        opt._es.stop = _fake_stop
        opt.ask(n=1)
        assert opt._restarts_used == 1
        assert id(opt._es) != first_es_id


# From test_optuna_adapter.py
# Unit tests for the Optuna optimizer adapter.
#
# Gated with ``pytest.importorskip`` so the test module is skipped if optuna
# is not available in the active environment (it is a core dependency, but
# this keeps the test robust to lightweight installs).


def _space_2d():
    return make_space(("K", 1e-6, 1e-3, "log"), ("Sy", 0.02, 0.30))


class TestOptunaAdapter:
    def test_fail_status_reported_to_optuna(self):
        opt = build_optimizer("optuna", _space_2d(), sampler="random", seed=0)
        s = opt.ask(1)[0]
        r = EvaluationResult(trial_id=s.trial_id, sim_id=None, cost=float("inf"), status="crashed")
        opt.tell([r])  # should not raise

    def test_rejects_unknown_sampler(self):
        with pytest.raises(ValueError, match="sampler"):
            build_optimizer("optuna", _space_2d(), sampler="not-a-sampler")

    @pytest.mark.parametrize(
        ("sampler", "width", "counts_the_trials_in_flight"),
        [("tpe", {}, False), ("tpe", {"width": 1}, False), ("tpe", {"width": 2}, True)]
        + [("tpe", {"width": 8}, True), ("random", {"width": 8}, False)],
    )
    def test_tpe_counts_the_trials_in_flight_from_a_width_of_two(
        self, sampler, width, counts_the_trials_in_flight
    ):
        with warnings.catch_warnings():
            # The option is experimental in Optuna, and the user is not told so. The
            # adapter sets its filter when the module is first imported, and a test
            # context drops it on exit, so the filter is set again here as it stands.
            warnings.simplefilter("error")
            warnings.filterwarnings("ignore", **optuna_adapter._EXPERIMENTAL_ARGUMENT)
            opt = build_optimizer("optuna", _space_2d(), sampler=sampler, seed=0, **width)
        assert getattr(opt._study.sampler, "_constant_liar", False) is counts_the_trials_in_flight


# From test_random_search_adapter.py
# Ask/tell loop, reproducibility, and best-tracking for ``random_search``.
#
# ``test_optim_optimizer.py`` already covers the ``n_samples`` kwarg rejection
# and the basic seeded-suggestion equality on a 2D space. This file adds the
# full ask/tell loop: independent optimizers with the same seed produce the same
# suggestion stream, ``tell`` accumulates history, ``best`` surfaces the lowest
# completed objective, and an unseeded optimizer behaves stochastically.


def _space__random_search() -> ParameterSpace:
    return make_space(("x", -3.0, 5.0), ("y", 10.0, 20.0))


def _log_space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(
                name="k", lower=1e-6, upper=1e-2, search_space="log", sampling="log_uniform"
            )
        ]
    )


def _quadratic(sugg: ParamSuggestion) -> EvaluationResult:
    """Convex bowl centered at (1.0, 15.0); objective >= 0, min at center."""
    x = float(sugg.values["x"])
    y = float(sugg.values["y"])
    cost = (x - 1.0) ** 2 + (y - 15.0) ** 2
    return EvaluationResult(
        trial_id=sugg.trial_id, sim_id=f"sim-{sugg.trial_id}", cost=cost, status="completed"
    )


class TestReproducibility:
    def test_two_independent_optimizers_same_seed_match(self) -> None:
        """A fixed seed gives identical suggestions across two optimizers."""
        opt_a = build_optimizer("random_search", _space__random_search(), seed=123)
        opt_b = build_optimizer("random_search", _space__random_search(), seed=123)
        sugg_a = opt_a.ask(n=8)
        sugg_b = opt_b.ask(n=8)
        assert len(sugg_a) == len(sugg_b) == 8
        for a, b in zip(sugg_a, sugg_b, strict=True):
            assert a.values["x"] == pytest.approx(b.values["x"])
            assert a.values["y"] == pytest.approx(b.values["y"])

    def test_seed_reproduces_across_ask_chunks(self) -> None:
        """Drawing in chunks yields the same stream as one big draw."""
        single = build_optimizer("random_search", _space__random_search(), seed=5)
        chunked = build_optimizer("random_search", _space__random_search(), seed=5)
        stream_single = single.ask(n=6)
        stream_chunked = chunked.ask(n=2) + chunked.ask(n=4)
        for a, b in zip(stream_single, stream_chunked, strict=True):
            assert a.values["x"] == pytest.approx(b.values["x"])
            assert a.values["y"] == pytest.approx(b.values["y"])


class TestBounds:
    def test_log_prior_samples_within_physical_bounds(self) -> None:
        opt = build_optimizer("random_search", _log_space(), seed=99)
        for s in opt.ask(n=200):
            assert 1e-6 <= s.values["k"] <= 1e-2


class TestTellAndBest:
    def test_best_tracks_lowest_completed_objective(self) -> None:
        """After telling many results, ``best`` matches the manual minimum."""
        opt = build_optimizer("random_search", _space__random_search(), seed=42)
        sugg = opt.ask(n=64)
        results = [_quadratic(s) for s in sugg]
        opt.tell(results)
        best = opt.best()
        assert best is not None
        expected = min(results, key=lambda r: r.cost)
        assert best.trial_id == expected.trial_id
        assert best.cost == pytest.approx(expected.cost)

    def test_tell_accumulates_history_across_batches(self) -> None:
        """``best`` reflects the global minimum over several tell batches."""
        opt = build_optimizer("random_search", _space__random_search(), seed=7)
        all_results: list[EvaluationResult] = []
        for _ in range(4):
            batch = [_quadratic(s) for s in opt.ask(n=16)]
            opt.tell(batch)
            all_results.extend(batch)
        best = opt.best()
        assert best is not None
        global_min = min(all_results, key=lambda r: r.cost)
        assert best.cost == pytest.approx(global_min.cost)

    def test_failed_trials_are_excluded_from_best(self) -> None:
        """Non-completed results never win even with a lower objective."""
        opt = build_optimizer("random_search", _space__random_search(), seed=1)
        sugg = opt.ask(n=2)
        good = EvaluationResult(
            trial_id=sugg[0].trial_id, sim_id="good", cost=10.0, status="completed"
        )
        cheaper_but_failed = EvaluationResult(
            trial_id=sugg[1].trial_id, sim_id="bad", cost=-1.0, status="failed"
        )
        opt.tell([good, cheaper_but_failed])
        best = opt.best()
        assert best is not None
        assert best.trial_id == good.trial_id
        assert best.cost == pytest.approx(10.0)


# From test_sweep_parallel.py
# Parallel sweep execution for the ``CalibrationEngine``.
#
# Drives ``CalibrationEngine.run`` with ``parallel > 1`` against an
# in-process fake optimizer and a deterministic evaluator. Confirms the
# engine returns the expected history and that trials run on distinct
# threads when ``parallel > 1``.


class _BatchedStubOptimizer:
    """Optimizer that serves one full batch of suggestions then stops."""

    name = "batched_stub"

    def __init__(self, suggestions: list[Mapping[str, float]]):
        self._suggestions = list(suggestions)
        self._trial_id = 0
        self._told: list[EvaluationResult] = []
        self._converged = False

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            if not self._suggestions:
                break
            values = self._suggestions.pop(0)
            self._trial_id += 1
            out.append(ParamSuggestion(trial_id=self._trial_id, values=dict(values)))
        return out

    def tell(self, results: list[EvaluationResult]) -> None:
        self._told.extend(results)
        # Stop after one round so the engine does not loop forever.
        self._converged = True

    def best(self) -> EvaluationResult | None:
        if not self._told:
            return None
        return min(self._told, key=lambda r: r.cost)

    def converged(self) -> bool:
        return self._converged


def _constant_evaluator(value: float):
    def _evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=f"sim-{sugg.trial_id:02d}",
            cost=float(sugg.values.get("x", value)),
            status="completed",
        )

    return _evaluator


@pytest.mark.parametrize(
    ("marks_after_reading", "told_at_journal"),
    [(False, 0), (True, 2)],
    ids=["as_trials_end", "after_the_batch_is_told"],
)
def test_a_parallel_batch_is_journaled_as_each_trial_ends_unless_the_engine_marks_after_reading(
    marks_after_reading: bool, told_at_journal: int
) -> None:
    optimizer = _BatchedStubOptimizer([{"x": 0.1}, {"x": 0.2}])
    if marks_after_reading:
        optimizer.marks_unread = True
    main = threading.get_ident()
    seen: list[tuple[int, bool, float]] = []
    updates: list[tuple[int, float]] = []
    reporter = SimpleNamespace(
        update=lambda trial_id, result: updates.append((trial_id, result.cost)),
        close=lambda: None,
    )

    run_engine(
        unit_space(),
        optimizer,
        _constant_evaluator(0.0),
        2,
        batch_size=2,
        parallel=2,
        progress=reporter,
        on_iteration=lambda sugg, result: seen.append(
            (len(optimizer._told), threading.get_ident() == main, result.cost)
        ),
    )

    assert sorted(seen) == [(told_at_journal, True, 0.1), (told_at_journal, True, 0.2)]
    assert sorted(updates) == [(1, 0.1), (2, 0.2)]


@pytest.mark.parametrize(
    ("method", "options", "parallel", "asked"),
    [
        ("grid", {"points_per_dim": 6}, 1, [1] * 6),
        ("grid", {"points_per_dim": 6}, 2, [6]),
        ("optuna", {"sampler": "random", "seed": 0}, 2, [2, 2, 2]),
        # One generation of five, then the one point the budget still allows.
        ("scipy_de", {"popsize": 5, "width": 2}, 2, [6, 1]),
    ],
    ids=[
        "grid_in_one_process",
        "grid_as_one_queue",
        "a_search_that_reads_results_keeps_batches",
        "a_generation_as_one_queue",
    ],
)
def test_a_fixed_plan_is_asked_whole_and_any_other_engine_in_batches(
    method, options, parallel, asked
) -> None:
    optimizer = build_optimizer(method, unit_space(), **options)
    sizes: list[int] = []
    ask = optimizer.ask
    optimizer.ask = lambda n=1: sizes.append(n) or ask(n)

    session = run_engine(unit_space(), optimizer, _constant_evaluator(0.0), 6, parallel=parallel)

    if hasattr(optimizer, "close"):
        optimizer.close()

    assert sizes == asked
    assert len(session.history) == 6


def test_an_idle_worker_takes_the_next_point_of_a_fixed_plan_while_a_slow_one_runs() -> None:
    third_started = threading.Event()

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        if sugg.trial_id == 3:
            third_started.set()
        if sugg.trial_id == 1:
            # With a barrier after two trials, the third waits for this one.
            assert third_started.wait(timeout=2.0)
        return _constant_evaluator(0.0)(sugg)

    optimizer = build_optimizer("grid", unit_space(), points_per_dim=4)
    session = run_engine(unit_space(), optimizer, evaluator, 4, parallel=2)

    assert [result.cost for result in session.history] == pytest.approx([0, 1 / 3, 2 / 3, 1])


def test_a_stop_reaches_the_solves_in_flight_before_the_engine_waits_for_them() -> None:
    stopped = threading.Event()

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        if sugg.trial_id == 2:
            # A solve in a worker that only the stop can end.
            assert stopped.wait(timeout=5.0)
        return _constant_evaluator(0.0)(sugg)

    def interrupt(*_: object) -> None:
        raise KeyboardInterrupt

    optimizer = _BatchedStubOptimizer([{"x": 0.1}, {"x": 0.2}])
    started = time.monotonic()
    with pytest.raises(KeyboardInterrupt):
        run_engine(
            unit_space(),
            optimizer,
            evaluator,
            2,
            batch_size=2,
            parallel=2,
            on_iteration=interrupt,
            on_stop=stopped.set,
        )

    assert time.monotonic() - started < 1.0


def test_a_stop_in_the_caller_thread_runs_no_queued_trial_and_keeps_the_journal() -> None:
    ran: list[int] = []
    journaled: list[int] = []
    release = threading.Event()

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        ran.append(sugg.trial_id)
        if sugg.trial_id > 1:
            assert release.wait(timeout=2.0)
        return _constant_evaluator(0.0)(sugg)

    def stop_after_the_first(sugg: ParamSuggestion, _result: EvaluationResult) -> None:
        journaled.append(sugg.trial_id)
        # The interrupt of the main thread, with the other worker still busy.
        threading.Timer(0.3, release.set).start()
        raise KeyboardInterrupt

    optimizer = _BatchedStubOptimizer([{"x": 0.1}, {"x": 0.2}, {"x": 0.3}, {"x": 0.4}])
    with pytest.raises(KeyboardInterrupt):
        run_engine(
            unit_space(),
            optimizer,
            evaluator,
            4,
            batch_size=4,
            parallel=2,
            on_iteration=stop_after_the_first,
        )

    assert journaled == [1]
    assert 4 not in ran


def test_a_parallel_batch_returns_its_results_in_order_and_journals_them_as_they_end() -> None:
    first_may_end = threading.Event()
    journaled: list[int] = []

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        if sugg.trial_id == 1:
            assert first_may_end.wait(timeout=2.0)
        return _constant_evaluator(0.0)(sugg)

    def journal(sugg: ParamSuggestion, _result: EvaluationResult) -> None:
        journaled.append(sugg.trial_id)
        first_may_end.set()

    class Ticks:
        trials: list[int] = []

        def update(self, trial_id: int, result: EvaluationResult) -> None:
            self.trials.append(trial_id)

        def close(self) -> None: ...

    ticks = Ticks()
    optimizer = _BatchedStubOptimizer([{"x": 0.1}, {"x": 0.2}])
    session = run_engine(
        unit_space(),
        optimizer,
        evaluator,
        2,
        batch_size=2,
        parallel=2,
        on_iteration=journal,
        progress=ticks,
    )

    assert journaled == [2, 1]
    # The bar moves as the trials end, not when the whole batch has.
    assert ticks.trials == [2, 1]
    assert [result.trial_id for result in session.history] == [1, 2]


# --------------------------------------------------------------------------- #
# suggest_next, the one-point form of the ask/tell protocol
# --------------------------------------------------------------------------- #
_LOG_K = ParameterSpace([CalibParameter(name="K", lower=1e-6, upper=1e-2, sampling="log_uniform")])


@pytest.mark.parametrize(
    ("name", "options"),
    [
        ("grid", {"points_per_dim": 2}),
        ("lhs", {"n_samples": 2, "seed": 1}),
        ("random_search", {"seed": 1}),
        ("optuna", {"seed": 1}),
        ("scipy_nelder_mead", {}),
        ("scipy_de", {"seed": 1}),
        ("cma_es", {"seed": 1}),
        ("gp_mapping", {"seed": 1, "n_init": 2}),
        ("da_mh_gp", {"seed": 1}),
    ],
)
def test_suggest_next_hands_out_the_first_point_of_the_search(name, options) -> None:
    adapter = build_optimizer(name, _LOG_K, **options)

    suggestion = adapter.suggest_next()

    assert suggestion.trial_id == 1
    assert list(suggestion.values) == ["K"]
    assert 1e-6 <= suggestion.values["K"] <= 1e-2


@pytest.mark.parametrize(
    ("name", "options"), [("grid", {"points_per_dim": 2}), ("lhs", {"n_samples": 2, "seed": 1})]
)
def test_suggest_next_says_when_a_fixed_design_is_spent(name, options) -> None:
    adapter = build_optimizer(name, _LOG_K, **options)
    adapter.suggest_next()
    adapter.suggest_next()

    with pytest.raises(StopIteration, match="exhausted"):
        adapter.suggest_next()


@pytest.mark.parametrize(
    ("name", "options", "match"),
    [
        ("grid", {"points_per_dim": [2, 3]}, "length must match"),
        ("lhs", {"n_samples": 0}, "must be positive, got 0"),
    ],
)
def test_a_design_that_does_not_fit_the_space_is_refused(name, options, match) -> None:
    with pytest.raises(ValueError, match=match):
        build_optimizer(name, _LOG_K, **options)


def test_a_signed_search_off_the_log_space_says_which_parameter_is_the_obstacle() -> None:
    choice = choose_method({"K": "identity"}, ["distance_gap"])

    assert (choice.method, choice.reason) == (
        "scipy_nelder_mead",
        "signed criterion, K not in log space, cost to minimise",
    )


def test_a_result_for_a_trial_optuna_never_asked_is_ignored() -> None:
    opt = build_optimizer("optuna", _LOG_K, seed=1)

    opt.tell([EvaluationResult(trial_id=9, sim_id=None, cost=1.0, status="completed")])

    assert opt.best() is None


def test_a_metric_nobody_registered_counts_as_unsigned() -> None:
    choice = choose_method({"K": "log"}, ["no_such_metric"])

    assert (choice.method, choice.reason) == ("scipy_nelder_mead", "cost to minimise")


def test_the_last_engine_answers_a_search_that_every_engine_refuses(monkeypatch) -> None:
    monkeypatch.setattr(
        optimizer_module, "engine_traits", lambda method: EngineTraits(max_parameters=1)
    )

    choice = choose_method({"K": "log", "Sy": "identity"}, ["rmse"])

    assert choice.method == "scipy_nelder_mead"
    assert choice.reason == "criterion on 2 parameters, cost to minimise"


def test_a_start_point_of_the_wrong_size_is_refused() -> None:
    with pytest.raises(OptimizerError, match="carries 2 value.*declares 1"):
        build_optimizer("scipy_nelder_mead", _LOG_K, start_at=[0.0, 1.0])
