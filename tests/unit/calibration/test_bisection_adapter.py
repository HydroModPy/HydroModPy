"""The one-dimensional root search, against a residual with a known root."""

from __future__ import annotations

import math

import pytest

from hydromodpy.calibration.adapters.bisection_adapter import (
    LOG10_ONE_PERCENT,
    BisectionAdapter,
    signed_residual,
)
from hydromodpy.calibration.optim.method_config import validate_method_kwargs
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    available_optimizers,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace

ROOT = 600.0
"""The truth the search must find, in physical units."""


def _space(lower: float = 1.0, upper: float = 1.0e5, name: str = "K") -> ParameterSpace:
    return ParameterSpace([CalibParameter(name=name, lower=lower, upper=upper, transform="log")])


def _evaluate(suggestion, *, root: float = ROOT, sign: float = 1.0) -> EvaluationResult:
    """A staircase residual: positive below the root, negative above it.

    A staircase on purpose, and one that never lands on zero. The real
    criterion is a step function that jumps over its root rather than reaching
    it, so a search leaning on a smooth residual would pass here and fail on a
    catchment.
    """
    value = float(next(iter(suggestion.values.values())))
    steps = math.floor(math.log10(root / value) * 20.0) + 0.5
    residual = sign * steps / 20.0
    return EvaluationResult(
        trial_id=suggestion.trial_id,
        sim_id=None,
        objective_value=abs(residual),
        status="completed",
        components={"net.J_signed": residual, "net.J": abs(residual)},
    )


def _run(adapter, *, max_iter: int = 40, **kwargs) -> list[EvaluationResult]:
    """Drive the adapter the way the engine does: ask, evaluate, tell."""
    history: list[EvaluationResult] = []
    while len(history) < max_iter:
        suggestions = adapter.ask(n=1)
        if not suggestions:
            break
        results = [_evaluate(sugg, **kwargs) for sugg in suggestions]
        history.extend(results)
        adapter.tell(results)
        if adapter.converged():
            break
    return history


class TestRegistration:
    def test_the_method_is_registered(self) -> None:
        assert "bisection" in available_optimizers()

    def test_its_kwargs_validate_against_the_frozen_union(self) -> None:
        config = validate_method_kwargs("bisection", {"sweep_points": 0, "rel_tol": 0.01})
        assert config.method == "bisection"

    def test_a_foreign_kwarg_is_refused_at_config_time(self) -> None:
        # Registering the adapter is not enough: without an entry in the union
        # a typo would only surface inside the constructor.
        with pytest.raises(Exception, match="popsize"):
            validate_method_kwargs("bisection", {"popsize": 6})

    def test_it_builds_through_the_registry(self) -> None:
        optimizer = build_optimizer("bisection", _space(), seed=42)
        assert isinstance(optimizer, BisectionAdapter)


class TestDimension:
    def test_a_two_parameter_space_is_refused(self) -> None:
        space = ParameterSpace(
            [
                CalibParameter(name="K", lower=1.0, upper=10.0),
                CalibParameter(name="Sy", lower=0.01, upper=0.3),
            ]
        )
        with pytest.raises(ValueError, match="searches one parameter"):
            BisectionAdapter(space)


class TestRootSearch:
    def test_it_closes_the_bracket_on_the_root(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=7)
        _run(adapter)

        assert adapter.converged()
        low, high = adapter.bracket
        assert low <= math.log10(ROOT) <= high
        assert high - low <= math.log10(1.01)

    def test_the_stopping_rule_is_the_bracket_and_not_the_residual(self) -> None:
        # The residual is a staircase that steps over zero without landing
        # on it, so a search stopping on its size would never stop.
        adapter = BisectionAdapter(_space(), sweep_points=0)
        history = _run(adapter)

        assert adapter.converged()
        # The residual never reaches zero, yet the search stops.
        assert min(abs(r.objective_value) for r in history) > 0.0
        low, high = adapter.bracket
        assert high - low <= math.log10(1.01)

    def test_the_budget_matches_the_arithmetic(self) -> None:
        # Five decades to close to one per cent: two ends plus
        # ceil(log2(5 / log10(1.01))) halvings.
        adapter = BisectionAdapter(_space(1.0, 1.0e5), sweep_points=0)
        history = _run(adapter)
        expected = 2 + math.ceil(math.log2(5.0 / LOG10_ONE_PERCENT))
        assert len(history) <= expected + 1

    def test_the_pure_bisection_of_the_paper_is_available(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=0)
        first = adapter.ask(n=4)
        # Only the two ends of the interval, whatever the batch size asks for.
        assert len(first) == 2

    def test_the_sweep_runs_before_the_bisection(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=7)
        assert len(adapter.ask(n=7)) == 7

    def test_the_best_trial_is_the_one_closest_to_zero(self) -> None:
        # The cost carries the absolute residual, so the lowest cost is the
        # nearest to the root and never the most negative one.
        adapter = BisectionAdapter(_space(), sweep_points=5)
        history = _run(adapter)
        best = adapter.best()
        assert best is not None
        assert best.objective_value == min(r.objective_value for r in history)

    def test_it_returns_an_evaluated_point_not_the_midpoint(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=5)
        history = _run(adapter)
        assert adapter.best().trial_id in {r.trial_id for r in history}


class TestRefusal:
    def test_a_bracket_without_a_sign_change_raises(self) -> None:
        adapter = BisectionAdapter(_space(1.0, 10.0), sweep_points=3, bracket_expand=0)
        with pytest.raises(ValueError, match="keeps the same sign"):
            # The root sits far above the interval, so every residual is positive.
            _run(adapter, root=1.0e9)

    def test_the_refusal_names_both_ends(self) -> None:
        adapter = BisectionAdapter(_space(1.0, 10.0), sweep_points=3, bracket_expand=0)
        with pytest.raises(ValueError) as failure:
            _run(adapter, root=1.0e9)
        message = str(failure.value)
        assert "J_signed" in message
        assert message.count("at K =") == 2

    def test_it_widens_the_bracket_before_giving_up(self) -> None:
        # The root is one decade above the declared interval: one expansion
        # finds it rather than refusing.
        adapter = BisectionAdapter(_space(1.0, 100.0), sweep_points=3, bracket_expand=4)
        _run(adapter, root=500.0)
        assert adapter.converged()
        low, high = adapter.bracket
        assert low <= math.log10(500.0) <= high

    def test_a_trial_without_the_signed_component_is_refused(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=0)
        suggestion = adapter.ask(n=1)[0]
        blind = EvaluationResult(
            trial_id=suggestion.trial_id,
            sim_id=None,
            objective_value=1.0,
            status="completed",
            components={"rmse": 1.0},
        )
        with pytest.raises(ValueError, match="published no 'J_signed'"):
            adapter.tell([blind])


class TestSignedComponentLookup:
    def test_a_bare_key_is_found(self) -> None:
        assert signed_residual({"J_signed": -2.0}) == -2.0

    def test_a_prefixed_key_is_found(self) -> None:
        assert signed_residual({"net.J_signed": 3.0}) == 3.0

    def test_two_candidates_are_an_error(self) -> None:
        with pytest.raises(ValueError, match="several outputs"):
            signed_residual({"a.J_signed": 1.0, "b.J_signed": 2.0})

    def test_an_absent_key_is_not_an_error_here(self) -> None:
        assert signed_residual({"rmse": 1.0}) is None
        assert signed_residual(None) is None
