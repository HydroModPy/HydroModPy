"""Optimizer factory and the ask/tell contract of every search method.

Suggestions are points of a parameter space (physical units of each parameter).
Costs are dimensionless. The engine tests run the batches in threads.
"""

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


def bowl_space() -> ParameterSpace:
    return make_space(("x", -2.0, 2.0), ("y", -2.0, 2.0))


def bowl_cost(values: dict) -> float:
    return 10.0 + float(values["x"]) ** 2 + float(values["y"]) ** 2


def tell_bowl(opt, sugg):
    opt.tell([result_of(sugg, bowl_cost(sugg.values))])


def test_confidence_bound_search_stops_when_bound_promises_nothing():
    # With kappa != 0 the score is the negated lower bound, negative for positive costs.
    opt = build_optimizer(
        "gp_mapping", bowl_space(), seed=11, n_init=4, max_trials=60, kappa=1.5, ei_tol=1e6
    )
    for _ in range(60):
        got = opt.ask(1)
        if not got:
            break
        tell_bowl(opt, got[0])
        if opt.converged():
            break
    assert opt.converged()
    assert len(opt._x_history) < 60


def test_confidence_bound_score_is_an_improvement():
    opt = build_optimizer("gp_mapping", bowl_space(), seed=11, n_init=4, max_trials=20, kappa=1.5)
    for _ in range(5):
        (sugg,) = opt.ask(1)
        tell_bowl(opt, sugg)
    opt.ask(1)
    assert opt._last_ei >= 0.0


def simplex_space() -> ParameterSpace:
    return make_space(("x", -1.0, 1.0), ("y", -1.0, 1.0))


def noise_evaluator():
    # A cost no simplex can settle on, so only the budget stops the search.
    rng = np.random.default_rng(5)

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        return result_of(sugg, float(rng.uniform(1.0, 2.0)))

    return evaluate


def run_simplex(max_trials: int, **options):
    optimizer = build_optimizer(
        "scipy_nelder_mead", simplex_space(), seed=1, xatol=0.0, fatol=0.0, **options
    )
    return run_engine(optimizer.space, optimizer, noise_evaluator(), max_trials)


def test_simplex_spends_a_budget_above_one_hundred():
    session = run_simplex(250)

    assert len(session.history) == 250
    assert not session.converged


def test_simplex_maxiter_still_stops_it():
    session = run_simplex(250, maxiter=20)

    assert len(session.history) < 250


@pytest.mark.parametrize("name", ["simplex", "nelder_mead"])
def test_removed_nelder_mead_names_are_refused(name):
    with pytest.raises(OptimizerError, match="Unknown optimizer"):
        build_optimizer(name, two_dim_space())


def test_grid_size_follows_points_per_dim():
    opt = build_optimizer("grid", two_dim_space(), points_per_dim=3)
    suggestions = opt.ask(n=9)
    values_x = [s.values["x"] for s in suggestions]
    values_y = [s.values["y"] for s in suggestions]
    assert len(suggestions) == 9
    assert min(values_x) == pytest.approx(0.0)
    assert max(values_x) == pytest.approx(1.0)
    assert min(values_y) == pytest.approx(-2.0)
    assert max(values_y) == pytest.approx(2.0)


def random_space() -> ParameterSpace:
    return make_space(("x", -3.0, 5.0), ("y", 10.0, 20.0))


def log_space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(
                name="k", lower=1e-6, upper=1e-2, search_space="log", sampling="log_uniform"
            )
        ]
    )


SAME_SEED = [
    pytest.param("lhs", two_dim_space, {"n_samples": 10, "seed": 42}, 10, id="lhs"),
    pytest.param("random_search", two_dim_space, {"seed": 7}, 4, id="random search"),
    pytest.param("random_search", random_space, {"seed": 123}, 8, id="random search, other space"),
]


@pytest.mark.parametrize(("method", "space", "options", "n"), SAME_SEED)
def test_same_seed_gives_the_same_points(method, space, options, n):
    first = build_optimizer(method, space(), **options).ask(n=n)
    second = build_optimizer(method, space(), **options).ask(n=n)
    assert len(first) == len(second) == n
    for a, b in zip(first, second, strict=True):
        assert a.values["x"] == pytest.approx(b.values["x"])
        assert a.values["y"] == pytest.approx(b.values["y"])


def test_another_seed_gives_another_lhs_design():
    xs_a = [
        p.values["x"]
        for p in build_optimizer("lhs", two_dim_space(), n_samples=10, seed=1).ask(n=10)
    ]
    xs_b = [
        p.values["x"]
        for p in build_optimizer("lhs", two_dim_space(), n_samples=10, seed=2).ask(n=10)
    ]
    assert xs_a != xs_b


def test_random_search_seed_holds_across_ask_chunks():
    single = build_optimizer("random_search", random_space(), seed=5)
    chunked = build_optimizer("random_search", random_space(), seed=5)
    stream_single = single.ask(n=6)
    stream_chunked = chunked.ask(n=2) + chunked.ask(n=4)
    for a, b in zip(stream_single, stream_chunked, strict=True):
        assert a.values["x"] == pytest.approx(b.values["x"])
        assert a.values["y"] == pytest.approx(b.values["y"])


def test_log_prior_stays_within_physical_bounds():
    opt = build_optimizer("random_search", log_space(), seed=99)
    for s in opt.ask(n=200):
        assert 1e-6 <= s.values["k"] <= 1e-2


@pytest.mark.parametrize(("engine", "options"), [("lhs", {"n_samples": 5}), ("optuna", {})])
def test_normal_prior_is_refused_naming_the_parameter(engine, options):
    space = ParameterSpace([CalibParameter(name="theta", lower=0.0, upper=1.0, sampling="normal")])
    with pytest.raises(ValueError, match=f"{engine} cannot draw.*theta"):
        build_optimizer(engine, space, seed=0, **options)


def test_lhs_is_exhausted_after_its_samples():
    opt = build_optimizer("lhs", two_dim_space(), n_samples=1, seed=0)
    opt.ask(n=1)
    with pytest.raises(StopIteration):
        opt.suggest_next()


def quadratic(sugg: ParamSuggestion) -> EvaluationResult:
    # Convex bowl centered at (1.0, 15.0), minimum 0 at the center.
    x = float(sugg.values["x"])
    y = float(sugg.values["y"])
    cost = (x - 1.0) ** 2 + (y - 15.0) ** 2
    return EvaluationResult(
        trial_id=sugg.trial_id, sim_id=f"sim-{sugg.trial_id}", cost=cost, status="completed"
    )


def test_lhs_best_is_lowest_completed_cost():
    opt = build_optimizer("lhs", two_dim_space(), n_samples=8, seed=3)
    results = [
        EvaluationResult(
            trial_id=s.trial_id,
            sim_id=f"sim-{s.trial_id}",
            cost=(s.values["x"] - 0.5) ** 2,
            status="completed",
        )
        for s in opt.ask(n=8)
    ]
    opt.tell(results)
    best = opt.best()
    assert best is not None
    assert best.trial_id == min(results, key=lambda r: r.cost).trial_id


def test_random_search_best_is_lowest_cost():
    opt = build_optimizer("random_search", random_space(), seed=42)
    results = [quadratic(s) for s in opt.ask(n=64)]
    opt.tell(results)
    best = opt.best()
    assert best is not None
    expected = min(results, key=lambda r: r.cost)
    assert best.trial_id == expected.trial_id
    assert best.cost == pytest.approx(expected.cost)


def test_best_over_several_tell_batches():
    opt = build_optimizer("random_search", random_space(), seed=7)
    all_results: list[EvaluationResult] = []
    for _ in range(4):
        batch = [quadratic(s) for s in opt.ask(n=16)]
        opt.tell(batch)
        all_results.extend(batch)
    best = opt.best()
    assert best is not None
    assert best.cost == pytest.approx(min(all_results, key=lambda r: r.cost).cost)


def test_failed_trials_never_win():
    opt = build_optimizer("random_search", random_space(), seed=1)
    sugg = opt.ask(n=2)
    good = EvaluationResult(trial_id=sugg[0].trial_id, sim_id="good", cost=10.0, status="completed")
    cheaper_but_failed = EvaluationResult(
        trial_id=sugg[1].trial_id, sim_id="bad", cost=-1.0, status="failed"
    )
    opt.tell([good, cheaper_but_failed])
    best = opt.best()
    assert best is not None
    assert best.trial_id == good.trial_id
    assert best.cost == pytest.approx(10.0)


def test_cma_restarts_when_it_stops_early():
    pytest.importorskip("cma")
    opt = build_optimizer(
        "cma_es", two_dim_space(), sigma0=0.25, popsize=4, max_trials=12, seed=2, restarts=1
    )
    first_es_id = id(opt._es)
    original_stop = opt._es.stop
    forced_stops = {"count": 0}

    def fake_stop():
        if forced_stops["count"] < 1:
            forced_stops["count"] += 1
            return {"forced": True}
        return original_stop()

    opt._es.stop = fake_stop
    opt.ask(n=1)
    assert opt._restarts_used == 1
    assert id(opt._es) != first_es_id


def optuna_space():
    return make_space(("K", 1e-6, 1e-3, "log"), ("Sy", 0.02, 0.30))


def test_optuna_accepts_a_crashed_trial():
    opt = build_optimizer("optuna", optuna_space(), sampler="random", seed=0)
    s = opt.ask(1)[0]
    opt.tell(
        [EvaluationResult(trial_id=s.trial_id, sim_id=None, cost=float("inf"), status="crashed")]
    )


def test_optuna_refuses_an_unknown_sampler():
    with pytest.raises(ValueError, match="sampler"):
        build_optimizer("optuna", optuna_space(), sampler="not-a-sampler")


# TPE counts the trials in flight from a width of two.
CONSTANT_LIAR = [
    pytest.param("tpe", {}, False, id="tpe, no width"),
    pytest.param("tpe", {"width": 1}, False, id="tpe, width one"),
    pytest.param("tpe", {"width": 2}, True, id="tpe, width two"),
    pytest.param("tpe", {"width": 8}, True, id="tpe, width eight"),
    pytest.param("random", {"width": 8}, False, id="random, width eight"),
]


@pytest.mark.parametrize(("sampler", "width", "counts_in_flight"), CONSTANT_LIAR)
def test_tpe_counts_trials_in_flight(sampler, width, counts_in_flight):
    with warnings.catch_warnings():
        # The option is experimental in Optuna, and the user is not told so. The
        # adapter sets its filter when the module is first imported, and a test
        # context drops it on exit, so the filter is set again here as it stands.
        warnings.simplefilter("error")
        warnings.filterwarnings("ignore", **optuna_adapter._EXPERIMENTAL_ARGUMENT)
        opt = build_optimizer("optuna", optuna_space(), sampler=sampler, seed=0, **width)
    assert getattr(opt._study.sampler, "_constant_liar", False) is counts_in_flight


# Parallel runs of the engine, against an in-process stub optimizer and a deterministic evaluator.


class BatchedStubOptimizer:
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

    def tell(self, results: list[EvaluationResult]):
        self._told.extend(results)
        # Stop after one round so the engine does not loop forever.
        self._converged = True

    def best(self) -> EvaluationResult | None:
        if not self._told:
            return None
        return min(self._told, key=lambda r: r.cost)

    def converged(self) -> bool:
        return self._converged


def constant_evaluator(value: float):
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
def test_parallel_batch_journal_timing(marks_after_reading: bool, told_at_journal: int):
    optimizer = BatchedStubOptimizer([{"x": 0.1}, {"x": 0.2}])
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
        constant_evaluator(0.0),
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
def test_ask_sizes(method, options, parallel, asked):
    optimizer = build_optimizer(method, unit_space(), **options)
    sizes: list[int] = []
    ask = optimizer.ask
    optimizer.ask = lambda n=1: sizes.append(n) or ask(n)

    session = run_engine(unit_space(), optimizer, constant_evaluator(0.0), 6, parallel=parallel)

    if hasattr(optimizer, "close"):
        optimizer.close()

    assert sizes == asked
    assert len(session.history) == 6


def test_idle_worker_takes_next_point():
    third_started = threading.Event()

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        if sugg.trial_id == 3:
            third_started.set()
        if sugg.trial_id == 1:
            # With a barrier after two trials, the third waits for this one.
            assert third_started.wait(timeout=2.0)
        return constant_evaluator(0.0)(sugg)

    optimizer = build_optimizer("grid", unit_space(), points_per_dim=4)
    session = run_engine(unit_space(), optimizer, evaluator, 4, parallel=2)

    assert [result.cost for result in session.history] == pytest.approx([0, 1 / 3, 2 / 3, 1])


def test_stop_reaches_solves_in_flight():
    stopped = threading.Event()

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        if sugg.trial_id == 2:
            # A solve in a worker that only the stop can end.
            assert stopped.wait(timeout=5.0)
        return constant_evaluator(0.0)(sugg)

    def interrupt(*_: object):
        raise KeyboardInterrupt

    optimizer = BatchedStubOptimizer([{"x": 0.1}, {"x": 0.2}])
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


def test_stop_in_caller_runs_no_queued_trial():
    ran: list[int] = []
    journaled: list[int] = []
    release = threading.Event()

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        ran.append(sugg.trial_id)
        if sugg.trial_id > 1:
            assert release.wait(timeout=2.0)
        return constant_evaluator(0.0)(sugg)

    def stop_after_the_first(sugg: ParamSuggestion, _result: EvaluationResult):
        journaled.append(sugg.trial_id)
        # The interrupt of the main thread, with the other worker still busy.
        threading.Timer(0.3, release.set).start()
        raise KeyboardInterrupt

    optimizer = BatchedStubOptimizer([{"x": 0.1}, {"x": 0.2}, {"x": 0.3}, {"x": 0.4}])
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


def test_parallel_batch_order_and_journal():
    first_may_end = threading.Event()
    journaled: list[int] = []

    def evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        if sugg.trial_id == 1:
            assert first_may_end.wait(timeout=2.0)
        return constant_evaluator(0.0)(sugg)

    def journal(sugg: ParamSuggestion, _result: EvaluationResult):
        journaled.append(sugg.trial_id)
        first_may_end.set()

    class Ticks:
        trials: list[int] = []

        def update(self, trial_id: int, result: EvaluationResult):
            self.trials.append(trial_id)

        def close(self): ...

    ticks = Ticks()
    optimizer = BatchedStubOptimizer([{"x": 0.1}, {"x": 0.2}])
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


# suggest_next is the one-point form of the ask/tell protocol.
LOG_K = ParameterSpace([CalibParameter(name="K", lower=1e-6, upper=1e-2, sampling="log_uniform")])


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
def test_first_suggestion(name, options):
    adapter = build_optimizer(name, LOG_K, **options)

    suggestion = adapter.suggest_next()

    assert suggestion.trial_id == 1
    assert list(suggestion.values) == ["K"]
    assert 1e-6 <= suggestion.values["K"] <= 1e-2


@pytest.mark.parametrize(
    ("name", "options"), [("grid", {"points_per_dim": 2}), ("lhs", {"n_samples": 2, "seed": 1})]
)
def test_fixed_design_exhausted(name, options):
    adapter = build_optimizer(name, LOG_K, **options)
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
def test_design_refusals(name, options, match):
    with pytest.raises(ValueError, match=match):
        build_optimizer(name, LOG_K, **options)


def test_signed_search_off_log_space():
    choice = choose_method({"K": "identity"}, ["distance_gap"])

    assert (choice.method, choice.reason) == (
        "scipy_nelder_mead",
        "signed criterion, K not in log space, cost to minimise",
    )


def test_optuna_ignores_unasked_trial():
    opt = build_optimizer("optuna", LOG_K, seed=1)

    opt.tell([EvaluationResult(trial_id=9, sim_id=None, cost=1.0, status="completed")])

    assert opt.best() is None


def test_unregistered_metric_is_unsigned():
    choice = choose_method({"K": "log"}, ["no_such_metric"])

    assert (choice.method, choice.reason) == ("scipy_nelder_mead", "cost to minimise")


def test_last_engine_answers_when_all_refuse(monkeypatch):
    monkeypatch.setattr(
        optimizer_module, "engine_traits", lambda method: EngineTraits(max_parameters=1)
    )

    choice = choose_method({"K": "log", "Sy": "identity"}, ["rmse"])

    assert choice.method == "scipy_nelder_mead"
    assert choice.reason == "criterion on 2 parameters, cost to minimise"


def test_start_point_of_the_wrong_size():
    with pytest.raises(OptimizerError, match="carries 2 value.*declares 1"):
        build_optimizer("scipy_nelder_mead", LOG_K, start_at=[0.0, 1.0])


# A start point on a bound still gets a simplex with distinct vertices. The vertex of an
# axis is the start plus 10 % of the range, clipped to the bounds.
def start_vertices(start_at) -> np.ndarray:
    space = make_space(("x", 0.0, 1.0), ("y", -2.0, 2.0))
    opt = build_optimizer("scipy_nelder_mead", space, seed=0, start_at=start_at)
    return np.array([[s.values["x"], s.values["y"]] for s in opt.ask(3)], dtype=float)


@pytest.mark.parametrize(
    "start_at",
    [[1.0, 0.0], [0.0, 2.0], [1.0, 2.0], [0.95, 1.9]],
    ids=["x on upper", "y on upper", "corner", "inside one step"],
)
def test_start_on_the_upper_bound_spans_the_space(start_at):
    vertices = start_vertices(start_at)

    assert len({tuple(v) for v in vertices}) == 3
    assert int(np.linalg.matrix_rank(vertices[1:] - vertices[0])) == 2


def test_start_inside_the_box_steps_up():
    vertices = start_vertices([0.5, 0.0])

    np.testing.assert_allclose(vertices[0], [0.5, 0.0])
    np.testing.assert_allclose(vertices[1], [0.6, 0.0])
    np.testing.assert_allclose(vertices[2], [0.5, 0.4])
