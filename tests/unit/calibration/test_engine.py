"""Unit tests for ``hydromodpy.calibration.engine``.

Ports the behavioural intent of the old ``test_calibration2_core.py``
to the new ask/tell architecture. The old engine took raw ``observed``
arrays and bounds dicts and dispatched a named method; the new engine
is solver-agnostic and takes ``space`` + ``optimizer`` + ``evaluator``.
Tests below cover the equivalent ground:

- history accumulation and ``session.best`` exposure,
- interaction with :class:`ParamsHashCache`,
- the ``on_iteration`` callback hook,
- graceful termination when the optimizer runs out of suggestions,
- edge cases ``max_iter=0`` and ``batch_size > max_iter``.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from hydromodpy.calibration.cache import ParamsHashCache, params_hash
from hydromodpy.calibration.engine import CalibrationEngine
from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace


def _unit_space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="x", lower=0.0, upper=1.0)])


def _simple_evaluator(sugg: ParamSuggestion) -> EvaluationResult:
    """Deterministic evaluator: objective = x, sim_id encodes trial_id."""
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=f"sim-{sugg.trial_id}",
        objective_value=float(sugg.values["x"]),
        status="completed",
    )


class _StubOptimizer:
    """Minimal ask/tell optimizer used to drive controlled scenarios.

    Implements the Protocol explicitly so we don't depend on how the
    built-in adapters happen to behave. ``suggestions`` is a list of
    parameter dicts served one at a time (per ``ask`` call).
    """

    name = "stub"

    def __init__(self, suggestions: list[Mapping[str, float]]):
        self._suggestions = list(suggestions)
        self._trial_id = 0
        self._history: list[EvaluationResult] = []
        self._exhausted = False

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            if not self._suggestions:
                self._exhausted = True
                break
            values = self._suggestions.pop(0)
            self._trial_id += 1
            out.append(ParamSuggestion(trial_id=self._trial_id, values=dict(values)))
        return out

    def tell(self, results: list[EvaluationResult]) -> None:
        self._history.extend(results)

    def suggest_next(self) -> ParamSuggestion:
        got = self.ask(1)
        if not got:
            raise StopIteration("stub exhausted")
        return got[0]

    def best(self) -> EvaluationResult | None:
        valid = [r for r in self._history if r.status == "completed"]
        if not valid:
            return None
        return min(valid, key=lambda r: r.objective_value)

    def converged(self) -> bool:
        return self._exhausted


# ---------------------------------------------------------------------------
# Engine orchestration
# ---------------------------------------------------------------------------


class TestEngineRun:
    def test_grid_iterates_until_exhausted(self):
        """Grid with 3 points must produce exactly 3 history entries."""
        space = _unit_space()
        opt = build_optimizer("grid", space, points_per_dim=3)
        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_simple_evaluator,
            max_iter=10,
        )
        session = engine.run()
        assert len(session.history) == 3
        assert {r.trial_id for r in session.history} == {1, 2, 3}

    def test_respects_max_iter_when_budget_is_binding(self):
        """``max_iter`` caps iterations even if the optimizer has more points."""
        space = _unit_space()
        opt = build_optimizer("grid", space, points_per_dim=20)
        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_simple_evaluator,
            max_iter=4,
        )
        session = engine.run()
        assert len(session.history) == 4

    def test_session_best_returns_lowest_objective(self):
        """``session.best`` must surface the best completed trial."""
        space = _unit_space()
        opt = build_optimizer("grid", space, points_per_dim=5)
        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_simple_evaluator,
            max_iter=100,
        )
        session = engine.run()
        assert session.best is not None
        # Grid spans [0.0, 1.0] with 5 points — min is 0.0.
        assert session.best.objective_value == pytest.approx(0.0)

    def test_session_exposes_duration(self):
        """Duration tracking does not break when the loop runs to completion."""
        space = _unit_space()
        opt = build_optimizer("grid", space, points_per_dim=2)
        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_simple_evaluator,
            max_iter=10,
        )
        session = engine.run()
        assert session.duration_s >= 0.0
        assert session.finished_at is not None


class TestEngineEdgeCases:
    def test_max_iter_zero_runs_no_iterations(self):
        """``max_iter=0`` must produce an empty session with no evaluator call."""
        space = _unit_space()
        opt = build_optimizer("grid", space, points_per_dim=5)
        calls: list[int] = []

        def _never(sugg):
            calls.append(sugg.trial_id)
            return _simple_evaluator(sugg)

        engine = CalibrationEngine(space=space, optimizer=opt, evaluator=_never, max_iter=0)
        session = engine.run()
        assert calls == []
        assert session.history == []
        assert session.best is None

    def test_batch_size_larger_than_max_iter_is_clamped(self):
        """When ``batch_size > max_iter`` the engine clamps the per-ask ``n``."""
        space = _unit_space()
        # Use a stub that returns 5 suggestions if asked — we expect only 3.
        opt = _StubOptimizer([{"x": 0.1}, {"x": 0.2}, {"x": 0.3}, {"x": 0.4}, {"x": 0.5}])
        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_simple_evaluator,
            max_iter=3,
            batch_size=100,
        )
        session = engine.run()
        assert len(session.history) == 3

    def test_empty_suggestion_list_terminates_without_error(self):
        """An optimizer that returns ``[]`` must stop the loop gracefully."""
        space = _unit_space()
        opt = _StubOptimizer(suggestions=[])

        def _never(sugg):
            raise RuntimeError("evaluator should not run when no suggestions")

        engine = CalibrationEngine(space=space, optimizer=opt, evaluator=_never, max_iter=10)
        session = engine.run()
        assert session.history == []
        assert session.best is None


# ---------------------------------------------------------------------------
# on_iteration callback
# ---------------------------------------------------------------------------


class TestOnIterationCallback:
    def test_callback_fires_once_per_completed_trial(self):
        space = _unit_space()
        opt = build_optimizer("grid", space, points_per_dim=4)
        received: list[int] = []

        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_simple_evaluator,
            max_iter=10,
            on_iteration=lambda r: received.append(r.trial_id),
        )
        engine.run()
        assert received == [1, 2, 3, 4]

    def test_callback_receives_evaluation_result_object(self):
        space = _unit_space()
        opt = build_optimizer("grid", space, points_per_dim=1)
        captured: list[EvaluationResult] = []

        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_simple_evaluator,
            max_iter=10,
            on_iteration=captured.append,
        )
        engine.run()
        assert len(captured) == 1
        result = captured[0]
        assert isinstance(result, EvaluationResult)
        assert result.status == "completed"


# ---------------------------------------------------------------------------
# ParamsHashCache integration
# ---------------------------------------------------------------------------


class TestEngineCacheIntegration:
    def test_cache_hit_skips_reevaluation(self):
        """Re-proposing the same values must not re-run the evaluator."""
        space = _unit_space()
        # Stub repeats the exact same values three times.
        opt = _StubOptimizer([{"x": 0.5}, {"x": 0.5}, {"x": 0.5}])
        cache = ParamsHashCache()
        eval_calls: list[int] = []

        def _counting_evaluator(sugg):
            eval_calls.append(sugg.trial_id)
            return EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id="sim-shared",
                objective_value=0.5,
                status="completed",
            )

        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_counting_evaluator,
            max_iter=10,
            cache=cache,
        )
        session = engine.run()
        assert len(eval_calls) == 1  # only the first call hits the evaluator
        assert len(session.history) == 3
        # Subsequent results must be marked as cache hits.
        assert session.history[0].from_cache is False
        assert session.history[1].from_cache is True
        assert session.history[2].from_cache is True
        assert session.history[1].status == "cached"
        # Cache is keyed by hash of the suggested values.
        assert params_hash({"x": 0.5}) in cache

    def test_cache_populates_with_sim_id_on_first_hit(self):
        """After the first completed evaluation, the cache holds its sim_id."""
        space = _unit_space()
        opt = _StubOptimizer([{"x": 0.42}])
        cache = ParamsHashCache()

        def _evaluator(sugg):
            return EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id="sim-abc",
                objective_value=0.1,
                status="completed",
            )

        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_evaluator,
            max_iter=10,
            cache=cache,
        )
        engine.run()
        key = params_hash({"x": 0.42})
        assert cache.get(key) == "sim-abc"

    def test_no_cache_means_every_trial_runs(self):
        """When ``cache=None`` the engine never inspects or stores results."""
        space = _unit_space()
        opt = _StubOptimizer([{"x": 0.5}, {"x": 0.5}, {"x": 0.5}])
        eval_calls: list[int] = []

        def _evaluator(sugg):
            eval_calls.append(sugg.trial_id)
            return _simple_evaluator(sugg)

        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_evaluator,
            max_iter=10,
            cache=None,
        )
        engine.run()
        assert len(eval_calls) == 3

    def test_cache_stores_params_hash_in_metadata(self):
        """Completed results should be enriched with ``params_hash`` metadata."""
        space = _unit_space()
        opt = _StubOptimizer([{"x": 0.25}])
        cache = ParamsHashCache()

        engine = CalibrationEngine(
            space=space,
            optimizer=opt,
            evaluator=_simple_evaluator,
            max_iter=5,
            cache=cache,
        )
        session = engine.run()
        assert len(session.history) == 1
        result = session.history[0]
        assert "params_hash" in result.metadata
        assert result.metadata["params_hash"] == params_hash({"x": 0.25})
