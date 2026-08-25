"""Parallel sweep execution for the ``CalibrationEngine``.

Drives ``CalibrationEngine.run`` with ``parallel > 1`` against an
in-process fake optimizer and a deterministic evaluator. Confirms the
engine returns the expected history and that trials run on distinct
threads when ``parallel > 1``.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace


def _unit_space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="x", lower=0.0, upper=1.0)])


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
        return min(self._told, key=lambda r: r.objective_value)

    def converged(self) -> bool:
        return self._converged


def _constant_evaluator(value: float):
    def _evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=f"sim-{sugg.trial_id:02d}",
            objective_value=float(sugg.values.get("x", value)),
            status="completed",
        )

    return _evaluator


def test_calibration_engine_parallel_four_trials() -> None:
    """``parallel=4`` runs four trials and records them in submission order."""
    space = _unit_space()
    optimizer = _BatchedStubOptimizer(suggestions=[{"x": 0.1}, {"x": 0.2}, {"x": 0.3}, {"x": 0.4}])
    engine = CalibrationEngine(
        space=space,
        optimizer=optimizer,
        evaluator=_constant_evaluator(0.0),
        max_iter=4,
        batch_size=4,
        parallel=4,
    )
    session = engine.run()
    assert len(session.history) == 4
    assert sorted(r.sim_id for r in session.history) == [
        "sim-01",
        "sim-02",
        "sim-03",
        "sim-04",
    ]
    assert sorted(r.objective_value for r in session.history) == [0.1, 0.2, 0.3, 0.4]


def test_calibration_engine_parallel_uses_threads() -> None:
    """A 4-trial batch with ``parallel=4`` lands on more than one thread."""
    barrier = threading.Barrier(4, timeout=2.0)
    seen: list[int] = []
    lock = threading.Lock()

    def _evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        barrier.wait()
        with lock:
            seen.append(threading.get_ident())
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=f"sim-{sugg.trial_id:02d}",
            objective_value=float(sugg.values["x"]),
            status="completed",
        )

    optimizer = _BatchedStubOptimizer(suggestions=[{"x": 0.5}, {"x": 0.6}, {"x": 0.7}, {"x": 0.8}])
    engine = CalibrationEngine(
        space=_unit_space(),
        optimizer=optimizer,
        evaluator=_evaluator,
        max_iter=4,
        batch_size=4,
        parallel=4,
    )
    engine.run()
    assert len(set(seen)) == 4


def test_calibration_engine_parallel_one_is_sequential() -> None:
    """``parallel=1`` keeps every trial on the calling thread."""
    main_thread = threading.get_ident()
    seen: list[int] = []

    def _evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        seen.append(threading.get_ident())
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=f"sim-{sugg.trial_id:02d}",
            objective_value=0.0,
            status="completed",
        )

    optimizer = _BatchedStubOptimizer(suggestions=[{"x": 0.1}, {"x": 0.2}, {"x": 0.3}, {"x": 0.4}])
    engine = CalibrationEngine(
        space=_unit_space(),
        optimizer=optimizer,
        evaluator=_evaluator,
        max_iter=4,
        batch_size=4,
        parallel=1,
    )
    engine.run()
    assert all(tid == main_thread for tid in seen)
