"""CalibrationEngine - orchestrates an ask/tell loop.

The engine is solver-agnostic and pipeline-agnostic: it takes a callable
``evaluator(values: dict[str, float]) -> EvaluationResult`` and runs the
ask/tell loop until the optimizer converges or ``max_iter`` is reached.

``save_runs`` modes (implemented via ``promote_best_n``):

- ``"none"``  (default): each iteration is **only** a DuckDB row. No Zarr.
- ``"best_n"``: after the loop, promote the top ``save_best_n`` iterations
                into full simulations (caller-supplied promoter callable).
- ``"all"``:   each iteration is already a full simulation.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from hydromodpy.calibration.cache import ParamsHashCache, params_hash
from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    Optimizer,
    ParamSuggestion,
)
from hydromodpy.calibration.parameters import ParameterSpace

EvaluatorFn = Callable[[ParamSuggestion], EvaluationResult]


class ProgressReporter(Protocol):
    def update(self, trial_id: int, result: EvaluationResult) -> None: ...
    def close(self) -> None: ...


class _NoopProgress:
    def update(self, trial_id: int, result: EvaluationResult) -> None: ...
    def close(self) -> None: ...


@dataclass
class CalibrationSession:
    """Outcome of a calibration run."""

    session_id: str
    optimizer: Optimizer
    space: ParameterSpace
    history: list[EvaluationResult] = field(default_factory=list)
    started_at: float = 0.0
    finished_at: float | None = None

    @property
    def best(self) -> EvaluationResult | None:
        return self.optimizer.best()

    @property
    def duration_s(self) -> float:
        end = self.finished_at or time.time()
        return end - self.started_at


@dataclass
class CalibrationEngine:
    """Drive an ask/tell loop until convergence or budget is exhausted.

    Minimal moving parts: ``space`` + ``optimizer`` + ``evaluator``. The
    engine only decides *when* to stop and which results to forward to the
    optimizer. Everything else (simulation, catalog, promotion) happens in
    the ``evaluator`` closure.
    """

    space: ParameterSpace
    optimizer: Optimizer
    evaluator: EvaluatorFn
    max_iter: int = 100
    batch_size: int = 1
    cache: ParamsHashCache | None = None
    progress: ProgressReporter | None = None
    session_id: str | None = None
    on_iteration: Callable[[EvaluationResult], None] | None = None

    def run(self) -> CalibrationSession:
        sid = self.session_id or uuid.uuid4().hex
        reporter = self.progress or _NoopProgress()
        session = CalibrationSession(
            session_id=sid,
            optimizer=self.optimizer,
            space=self.space,
            started_at=time.time(),
        )
        try:
            n_done = 0
            while n_done < self.max_iter:
                take = min(self.batch_size, self.max_iter - n_done)
                suggestions = self.optimizer.ask(n=take)
                if not suggestions:
                    break
                results: list[EvaluationResult] = []
                for sugg in suggestions:
                    result = self._evaluate_with_cache(sugg)
                    results.append(result)
                    session.history.append(result)
                    reporter.update(sugg.trial_id, result)
                    if self.on_iteration is not None:
                        self.on_iteration(result)
                self.optimizer.tell(results)
                n_done += len(results)
                if self.optimizer.converged():
                    break
        finally:
            session.finished_at = time.time()
            reporter.close()
        return session

    def _evaluate_with_cache(self, sugg: ParamSuggestion) -> EvaluationResult:
        if self.cache is None:
            return self._with_parameter_metadata(self.evaluator(sugg), sugg)
        key = params_hash(sugg.values)
        hit = self.cache.get(key)
        if hit is not None:
            return EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=hit.sim_id,
                objective_value=hit.objective_value,
                status="completed",
                from_cache=True,
                components=hit.components,
                metadata={
                    "params_hash": key,
                    "cached_status": hit.status,
                    "parameters": self.space.describe_values(sugg.values),
                },
            )
        result = self.evaluator(sugg)
        if result.status == "completed" and math.isfinite(result.objective_value):
            self.cache.put(
                key,
                result.sim_id,
                objective_value=result.objective_value,
                components=result.components,
            )
        # Enrich metadata with hash for persistence.
        meta = dict(result.metadata or {})
        meta.setdefault("params_hash", key)
        meta.setdefault("parameters", self.space.describe_values(sugg.values))
        return EvaluationResult(
            trial_id=result.trial_id,
            sim_id=result.sim_id,
            objective_value=result.objective_value,
            status=result.status,
            duration_s=result.duration_s,
            components=result.components,
            from_cache=result.from_cache,
            metadata=meta,
        )

    def _with_parameter_metadata(
        self,
        result: EvaluationResult,
        sugg: ParamSuggestion,
    ) -> EvaluationResult:
        meta = dict(result.metadata or {})
        meta.setdefault("parameters", self.space.describe_values(sugg.values))
        return EvaluationResult(
            trial_id=result.trial_id,
            sim_id=result.sim_id,
            objective_value=result.objective_value,
            status=result.status,
            duration_s=result.duration_s,
            components=result.components,
            from_cache=result.from_cache,
            metadata=meta,
        )


__all__ = [
    "CalibrationEngine",
    "CalibrationSession",
    "EvaluatorFn",
]
