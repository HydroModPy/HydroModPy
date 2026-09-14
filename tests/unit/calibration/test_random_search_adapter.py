"""Ask/tell loop, reproducibility, and best-tracking for ``random_search``.

``test_adapter_aliases.py`` already covers the ``n_samples`` kwarg rejection
and the basic seeded-suggestion equality on a 2D space. This file adds the
full ask/tell loop: independent optimizers with the same seed produce the same
suggestion stream, ``tell`` accumulates history, ``best`` surfaces the lowest
completed objective, and an unseeded optimizer behaves stochastically.
"""

from __future__ import annotations

import pytest

from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace


def _space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=-3.0, upper=5.0),
            CalibParameter(name="y", lower=10.0, upper=20.0),
        ]
    )


def _log_space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(
                name="k",
                lower=1e-6,
                upper=1e-2,
                transform="log",
                prior="log_uniform",
            ),
        ]
    )


def _quadratic(sugg: ParamSuggestion) -> EvaluationResult:
    """Convex bowl centred at (1.0, 15.0); objective >= 0, min at centre."""
    x = float(sugg.values["x"])
    y = float(sugg.values["y"])
    cost = (x - 1.0) ** 2 + (y - 15.0) ** 2
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=f"sim-{sugg.trial_id}",
        objective_value=cost,
        status="completed",
    )


class TestReproducibility:
    def test_two_independent_optimizers_same_seed_match(self) -> None:
        """A fixed seed gives identical suggestions across two optimizers."""
        opt_a = build_optimizer("random_search", _space(), seed=123)
        opt_b = build_optimizer("random_search", _space(), seed=123)
        sugg_a = opt_a.ask(n=8)
        sugg_b = opt_b.ask(n=8)
        assert len(sugg_a) == len(sugg_b) == 8
        for a, b in zip(sugg_a, sugg_b, strict=True):
            assert a.values["x"] == pytest.approx(b.values["x"])
            assert a.values["y"] == pytest.approx(b.values["y"])

    def test_seed_reproduces_across_ask_chunks(self) -> None:
        """Drawing in chunks yields the same stream as one big draw."""
        single = build_optimizer("random_search", _space(), seed=5)
        chunked = build_optimizer("random_search", _space(), seed=5)
        stream_single = single.ask(n=6)
        stream_chunked = chunked.ask(n=2) + chunked.ask(n=4)
        for a, b in zip(stream_single, stream_chunked, strict=True):
            assert a.values["x"] == pytest.approx(b.values["x"])
            assert a.values["y"] == pytest.approx(b.values["y"])

    def test_different_seeds_diverge(self) -> None:
        """Distinct seeds must not collapse to the same suggestion stream."""
        opt_a = build_optimizer("random_search", _space(), seed=1)
        opt_b = build_optimizer("random_search", _space(), seed=2)
        xs_a = [s.values["x"] for s in opt_a.ask(n=10)]
        xs_b = [s.values["x"] for s in opt_b.ask(n=10)]
        assert xs_a != xs_b

    def test_unseeded_optimizers_are_stochastic(self) -> None:
        """Without a seed two optimizers diverge with overwhelming odds."""
        opt_a = build_optimizer("random_search", _space())
        opt_b = build_optimizer("random_search", _space())
        xs_a = [s.values["x"] for s in opt_a.ask(n=10)]
        xs_b = [s.values["x"] for s in opt_b.ask(n=10)]
        assert xs_a != xs_b


class TestAskContract:
    def test_ask_returns_requested_count(self) -> None:
        opt = build_optimizer("random_search", _space(), seed=0)
        assert len(opt.ask(n=1)) == 1
        assert len(opt.ask(n=7)) == 7

    def test_ask_default_is_one(self) -> None:
        opt = build_optimizer("random_search", _space(), seed=0)
        assert len(opt.ask()) == 1

    def test_trial_ids_are_unique_and_monotonic(self) -> None:
        opt = build_optimizer("random_search", _space(), seed=0)
        sugg = opt.ask(n=3) + opt.ask(n=3)
        ids = [s.trial_id for s in sugg]
        assert ids == sorted(ids)
        assert len(set(ids)) == len(ids)

    def test_suggest_next_returns_single_suggestion(self) -> None:
        opt = build_optimizer("random_search", _space(), seed=0)
        s = opt.suggest_next()
        assert isinstance(s, ParamSuggestion)
        assert set(s.values) == {"x", "y"}

    def test_suggestions_carry_every_parameter(self) -> None:
        opt = build_optimizer("random_search", _space(), seed=3)
        for s in opt.ask(n=5):
            assert set(s.values) == {"x", "y"}
            assert s.source == "ask"


class TestBounds:
    def test_uniform_samples_within_physical_bounds(self) -> None:
        opt = build_optimizer("random_search", _space(), seed=99)
        for s in opt.ask(n=200):
            assert -3.0 <= s.values["x"] <= 5.0
            assert 10.0 <= s.values["y"] <= 20.0

    def test_log_prior_samples_within_physical_bounds(self) -> None:
        opt = build_optimizer("random_search", _log_space(), seed=99)
        for s in opt.ask(n=200):
            assert 1e-6 <= s.values["k"] <= 1e-2


class TestTellAndBest:
    def test_best_is_none_before_any_tell(self) -> None:
        opt = build_optimizer("random_search", _space(), seed=0)
        opt.ask(n=3)
        assert opt.best() is None

    def test_best_tracks_lowest_completed_objective(self) -> None:
        """After telling many results, ``best`` matches the manual minimum."""
        opt = build_optimizer("random_search", _space(), seed=42)
        sugg = opt.ask(n=64)
        results = [_quadratic(s) for s in sugg]
        opt.tell(results)
        best = opt.best()
        assert best is not None
        expected = min(results, key=lambda r: r.objective_value)
        assert best.trial_id == expected.trial_id
        assert best.objective_value == pytest.approx(expected.objective_value)

    def test_tell_accumulates_history_across_batches(self) -> None:
        """``best`` reflects the global minimum over several tell batches."""
        opt = build_optimizer("random_search", _space(), seed=7)
        all_results: list[EvaluationResult] = []
        for _ in range(4):
            batch = [_quadratic(s) for s in opt.ask(n=16)]
            opt.tell(batch)
            all_results.extend(batch)
        best = opt.best()
        assert best is not None
        global_min = min(all_results, key=lambda r: r.objective_value)
        assert best.objective_value == pytest.approx(global_min.objective_value)

    def test_random_search_approaches_convex_minimum(self) -> None:
        """Dense random sampling of a convex bowl gets close to the optimum."""
        opt = build_optimizer("random_search", _space(), seed=2024)
        results = [_quadratic(s) for s in opt.ask(n=2000)]
        opt.tell(results)
        best = opt.best()
        assert best is not None
        # Min cost is 0 at (1, 15); 2000 uniform draws over an 8x10 box land
        # comfortably below this loose bound without touching the optimum.
        assert best.objective_value < 0.5

    def test_failed_trials_are_excluded_from_best(self) -> None:
        """Non-completed results never win even with a lower objective."""
        opt = build_optimizer("random_search", _space(), seed=1)
        sugg = opt.ask(n=2)
        good = EvaluationResult(
            trial_id=sugg[0].trial_id,
            sim_id="good",
            objective_value=10.0,
            status="completed",
        )
        cheaper_but_failed = EvaluationResult(
            trial_id=sugg[1].trial_id,
            sim_id="bad",
            objective_value=-1.0,
            status="failed",
        )
        opt.tell([good, cheaper_but_failed])
        best = opt.best()
        assert best is not None
        assert best.trial_id == good.trial_id
        assert best.objective_value == pytest.approx(10.0)

    def test_best_is_none_when_all_trials_failed(self) -> None:
        opt = build_optimizer("random_search", _space(), seed=1)
        sugg = opt.ask(n=2)
        opt.tell(
            [
                EvaluationResult(
                    trial_id=s.trial_id,
                    sim_id=None,
                    objective_value=0.0,
                    status="failed",
                )
                for s in sugg
            ]
        )
        assert opt.best() is None


class TestConvergence:
    def test_never_reports_converged(self) -> None:
        """Random search has no stopping rule; the engine bounds the budget."""
        opt = build_optimizer("random_search", _space(), seed=0)
        assert opt.converged() is False
        opt.tell([_quadratic(s) for s in opt.ask(n=10)])
        assert opt.converged() is False


class TestInvalidArgs:
    def test_unknown_kwarg_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            build_optimizer("random_search", _space(), population=4)

    def test_seed_must_be_keyword_only(self) -> None:
        with pytest.raises(TypeError):
            build_optimizer("random_search", _space(), 0)  # type: ignore[misc]
