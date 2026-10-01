"""Stratification, reproducibility, and budget contract for ``lhs``.

``lhs`` draws a true stratified Latin hypercube design, once, in the unit
hypercube, then maps each dimension into its parameter's transformed space.
Unlike ``random_search`` (independent per-dimension draws), every one of the
``n_samples`` strata of every dimension is hit exactly once: that guarantee,
not just "within bounds", is what these tests check.
"""

from __future__ import annotations

import math

import pytest

from hydromodpy.calibration.optim.method_config import (
    LhsMethodConfig,
    validate_method_kwargs,
)
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import resolve_budget, short_budget


def _space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=0.0, upper=1.0),
            CalibParameter(name="y", lower=-2.0, upper=2.0),
        ]
    )


def _log_space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="k", lower=1e-6, upper=1e-2, transform="log")])


def _strata_indices(values: list[float], low: float, high: float, n: int) -> list[int]:
    """Bin each value into one of *n* equal-width strata of [low, high]."""
    width = (high - low) / n
    return sorted(min(int((v - low) / width), n - 1) for v in values)


class TestStratification:
    def test_each_stratum_is_hit_exactly_once_per_dimension(self) -> None:
        n = 12
        opt = build_optimizer("lhs", _space(), n_samples=n, seed=0)
        points = opt.ask(n=n)
        xs = [p.values["x"] for p in points]
        ys = [p.values["y"] for p in points]
        assert _strata_indices(xs, 0.0, 1.0, n) == list(range(n))
        assert _strata_indices(ys, -2.0, 2.0, n) == list(range(n))

    def test_log_transform_stratifies_log10_space(self) -> None:
        n = 10
        opt = build_optimizer("lhs", _log_space(), n_samples=n, seed=1)
        points = opt.ask(n=n)
        logs = [math.log10(p.values["k"]) for p in points]
        assert _strata_indices(logs, -6.0, -2.0, n) == list(range(n))

    def test_bounds_are_respected(self) -> None:
        opt = build_optimizer("lhs", _space(), n_samples=50, seed=2)
        for p in opt.ask(n=50):
            assert 0.0 <= p.values["x"] <= 1.0
            assert -2.0 <= p.values["y"] <= 2.0

    def test_normal_prior_is_refused_naming_the_parameter(self) -> None:
        space = ParameterSpace([CalibParameter(name="theta", lower=0.0, upper=1.0, prior="normal")])
        with pytest.raises(ValueError, match="theta"):
            build_optimizer("lhs", space, n_samples=5, seed=0)

    def test_random_cd_optimization_keeps_the_stratification_guarantee(self) -> None:
        n = 12
        opt = build_optimizer("lhs", _space(), n_samples=n, seed=0, optimization="random-cd")
        points = opt.ask(n=n)
        xs = [p.values["x"] for p in points]
        assert _strata_indices(xs, 0.0, 1.0, n) == list(range(n))

    def test_lloyd_optimization_is_not_guaranteed_to_keep_every_stratum(self) -> None:
        # scipy's Lloyd relaxation trades the one-point-per-stratum guarantee
        # for better point spacing: this seed is a known case where several
        # strata of "x" are left unsampled, which is why "lloyd" is documented
        # as a best-effort post-process rather than an exact design.
        n = 12
        opt = build_optimizer("lhs", _space(), n_samples=n, seed=0, optimization="lloyd")
        points = opt.ask(n=n)
        xs = [p.values["x"] for p in points]
        assert _strata_indices(xs, 0.0, 1.0, n) != list(range(n))


class TestReproducibility:
    def test_same_seed_gives_the_same_design(self) -> None:
        opt_a = build_optimizer("lhs", _space(), n_samples=10, seed=42)
        opt_b = build_optimizer("lhs", _space(), n_samples=10, seed=42)
        a = opt_a.ask(n=10)
        b = opt_b.ask(n=10)
        for pa, pb in zip(a, b, strict=True):
            assert pa.values["x"] == pytest.approx(pb.values["x"])
            assert pa.values["y"] == pytest.approx(pb.values["y"])

    def test_another_seed_gives_a_different_design(self) -> None:
        opt_a = build_optimizer("lhs", _space(), n_samples=10, seed=1)
        opt_b = build_optimizer("lhs", _space(), n_samples=10, seed=2)
        xs_a = [p.values["x"] for p in opt_a.ask(n=10)]
        xs_b = [p.values["x"] for p in opt_b.ask(n=10)]
        assert xs_a != xs_b


class TestAskContract:
    def test_ask_returns_batches_and_then_exhausts(self) -> None:
        opt = build_optimizer("lhs", _space(), n_samples=5, seed=0)
        first = opt.ask(n=3)
        assert len(first) == 3
        assert opt.converged() is False
        second = opt.ask(n=3)
        assert len(second) == 2
        assert opt.converged() is True
        assert opt.ask(n=1) == []

    def test_trial_ids_are_unique_and_monotonic(self) -> None:
        opt = build_optimizer("lhs", _space(), n_samples=6, seed=0)
        ids = [p.trial_id for p in opt.ask(n=3) + opt.ask(n=3)]
        assert ids == sorted(ids)
        assert len(set(ids)) == len(ids)

    def test_suggest_next_raises_once_exhausted(self) -> None:
        opt = build_optimizer("lhs", _space(), n_samples=1, seed=0)
        opt.ask(n=1)
        with pytest.raises(StopIteration):
            opt.suggest_next()


class TestTellAndBest:
    def test_best_tracks_lowest_completed_objective(self) -> None:
        opt = build_optimizer("lhs", _space(), n_samples=8, seed=3)
        suggestions = opt.ask(n=8)
        results = [
            EvaluationResult(
                trial_id=s.trial_id,
                sim_id=f"sim-{s.trial_id}",
                objective_value=(s.values["x"] - 0.5) ** 2,
                status="completed",
            )
            for s in suggestions
        ]
        opt.tell(results)
        best = opt.best()
        expected = min(results, key=lambda r: r.objective_value)
        assert best is not None
        assert best.trial_id == expected.trial_id


class TestBudget:
    def test_auto_resolves_to_n_samples(self) -> None:
        opt = build_optimizer("lhs", _space(), n_samples=17, seed=0)
        assert resolve_budget(opt, "auto") == 17

    def test_written_max_iter_below_n_samples_is_refused(self) -> None:
        opt = build_optimizer("lhs", _space(), n_samples=17, seed=0)
        verdict = short_budget(opt.counted_budget, 10)
        assert verdict is not None
        severity, message = verdict
        assert severity == "error"
        assert "17" in message

    def test_written_max_iter_at_or_above_n_samples_is_accepted(self) -> None:
        opt = build_optimizer("lhs", _space(), n_samples=17, seed=0)
        assert short_budget(opt.counted_budget, 17) is None
        assert short_budget(opt.counted_budget, 30) is None


class TestMethodConfig:
    def test_n_samples_is_required(self) -> None:
        with pytest.raises(Exception):
            validate_method_kwargs("lhs", {})

    def test_n_samples_and_optimization_validate(self) -> None:
        cfg = validate_method_kwargs("lhs", {"n_samples": 20, "optimization": "random-cd"})
        assert isinstance(cfg, LhsMethodConfig)
        assert cfg.n_samples == 20
        assert cfg.optimization == "random-cd"

    def test_extra_key_is_refused(self) -> None:
        with pytest.raises(Exception, match="popsize"):
            validate_method_kwargs("lhs", {"n_samples": 10, "popsize": 5})

    def test_non_positive_n_samples_is_refused(self) -> None:
        with pytest.raises(Exception):
            validate_method_kwargs("lhs", {"n_samples": 0})
