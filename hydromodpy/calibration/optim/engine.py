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
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass, field
from typing import Any, Protocol

from hydromodpy.calibration.optim.cache import ParamsHashCache, params_hash
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    Optimizer,
    ParamSuggestion,
)
from hydromodpy.calibration.optim.parameters import ParameterSpace

EvaluatorFn = Callable[[ParamSuggestion], EvaluationResult]


class ProgressReporter(Protocol):
    def update(self, trial_id: int, result: EvaluationResult) -> None: ...
    def close(self) -> None: ...


class _NoopProgress:
    def update(self, trial_id: int, result: EvaluationResult) -> None: ...
    def close(self) -> None: ...


@dataclass
class CalibrationSession:
    """Runtime result returned after a calibration loop.

    The session keeps the optimizer instance, the calibrated parameter space,
    every evaluation result, and timing metadata. Use ``best`` for the current
    minimum-cost evaluation and ``duration_s`` for elapsed wall-clock time.
    """

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

    The evaluator receives a ``ParamSuggestion`` and returns an
    ``EvaluationResult``. Optional caching uses a parameter hash so repeated
    candidates can reuse previous objective values.
    """

    space: ParameterSpace
    optimizer: Optimizer
    evaluator: EvaluatorFn
    max_iter: int = 100
    batch_size: int = 1
    parallel: int = 1
    cache: ParamsHashCache | None = None
    cache_context: Mapping[str, Any] | None = None
    progress: ProgressReporter | None = None
    session_id: str | None = None
    on_iteration: Callable[[ParamSuggestion, EvaluationResult], None] | None = None
    """Called once per evaluated suggestion, cache hits included.

    Takes the suggestion alongside its result: a cache hit never reaches the
    evaluator, so the caller has no other way to know which parameters the
    iteration carried, and the row it persists would be dropped.
    """

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
                results = self._evaluate_batch(suggestions)
                for sugg, result in zip(suggestions, results, strict=True):
                    session.history.append(result)
                    reporter.update(sugg.trial_id, result)
                    if self.on_iteration is not None:
                        self.on_iteration(sugg, result)
                self.optimizer.tell(results)
                n_done += len(results)
                if self.optimizer.converged():
                    break
        finally:
            session.finished_at = time.time()
            reporter.close()
            close_optimizer = getattr(self.optimizer, "close", None)
            if callable(close_optimizer):
                close_optimizer()
        return session

    def _evaluate_batch(
        self,
        suggestions: list[ParamSuggestion],
    ) -> list[EvaluationResult]:
        """Run every suggestion of one batch and return their results in order.

        ``parallel <= 1`` keeps the legacy sequential loop. ``parallel > 1``
        dispatches trials through a :class:`ThreadPoolExecutor`. Threads
        are used over processes because evaluators close over a live
        ``Project`` whose DuckDB connection and Zarr handles are not
        pickle-safe.
        """
        if self.parallel <= 1 or len(suggestions) <= 1:
            return [self._evaluate_with_cache(sugg) for sugg in suggestions]
        workers = min(self.parallel, len(suggestions))
        # ContextVars (e.g. the api-isolation scope the caller opened) do NOT cross
        # the thread boundary, so give each worker its own copy of THIS thread's
        # context. copy_context() runs here, in the caller thread, so every copy
        # inherits the current bindings; a fresh copy per task avoids entering one
        # Context object from several threads at once.
        tasks = [(copy_context(), sugg) for sugg in suggestions]

        def _run_in_context(item: tuple) -> EvaluationResult:
            ctx, sugg = item
            return ctx.run(self._evaluate_with_cache, sugg)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(_run_in_context, tasks))

    def _evaluate_with_cache(self, sugg: ParamSuggestion) -> EvaluationResult:
        if self.cache is None:
            return self._with_parameter_metadata(self.evaluator(sugg), sugg)
        key = params_hash(sugg.values, context=self.cache_context)
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
