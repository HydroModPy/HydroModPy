"""CalibrationEngine - orchestrates an ask/tell loop.

The engine is solver-agnostic and pipeline-agnostic: it takes a callable
``evaluator(values: dict[str, float]) -> EvaluationResult`` and runs the
ask/tell loop until the optimizer converges or ``max_iter`` is reached.

``save_runs`` modes (implemented via ``promote_best_n``):

- ``"none"``  (default): each iteration is **only** a DuckDB row. No Zarr.
- ``"best_n"``: after the loop, promote the top ``save_best_n`` iterations
                into full simulations (caller-supplied promoter callable).
- ``"all"``:   each iteration is already a full simulation.

Running out of budget is not converging. An engine that declares a stopping
option (:func:`hydromodpy.calibration.optim.stopping.stopping_rule`) and
reaches ``max_iter`` before meeting it has not converged: the session says so
in ``converged`` and the caller decides what that means, a staged calibration
freezes nothing from it. An engine whose only rule is its budget converges
when the budget is spent.

An engine that can count its evaluations before the first solve publishes a
``counted_budget`` (:class:`~hydromodpy.calibration.optim.stopping.CountedBudget`).
Only the root search does: ``max_iter = "auto"`` then runs its worst case, a
declared budget below its nominal case is refused before anything solves, one
below its worst case is announced, and a budget that still runs out is extended
once by exactly the ``evaluations_remaining`` the engine reports, never by a
fraction of the budget. Every other engine gets no extension: re-running with a
larger ``max_iter`` replays the trials already solved from the params-hash
cache.
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
from hydromodpy.calibration.optim.stopping import (
    BUDGET_RULE,
    CountedBudget,
    remaining_grant,
    resolve_budget,
    short_budget,
    stopping_rule,
)
from hydromodpy.core.exceptions import OptimizerError
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

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
    stopping_rule: str = BUDGET_RULE
    """The rule the engine stops on: its stopping option, or ``"budget"``."""
    converged: bool = False
    """Whether the search met ``stopping_rule`` before its budget ran out.

    Set once the loop ends. A budget-only engine converges when it spends its
    budget; any other engine only when its own rule says so.
    """
    max_iter: int = 0
    """The budget the engine ran with, ``"auto"`` resolved, before any extension."""
    extension: int = 0
    """Evaluations granted beyond ``max_iter``: zero, or what a counting engine
    still needed when its budget ran out, once."""

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
    max_iter: int | str = 100
    """The evaluation budget, or ``"auto"`` to let a counting engine size it."""
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
        budget = resolve_budget(self.optimizer, self.max_iter)
        session = CalibrationSession(
            session_id=sid,
            optimizer=self.optimizer,
            space=self.space,
            started_at=time.time(),
            stopping_rule=stopping_rule(self.optimizer),
            max_iter=budget,
        )
        judged = session.stopping_rule != BUDGET_RULE
        try:
            if judged:
                self._judge_the_budget(budget)
            ran_dry = self._run_until(budget, 0, session, reporter)
            if judged and not ran_dry and not self.optimizer.converged():
                session.extension = self._extension(budget, session)
                if session.extension:
                    self._run_until(
                        budget + session.extension, len(session.history), session, reporter
                    )
            session.converged = (not judged) or bool(self.optimizer.converged())
            if not session.converged:
                logger.warning(
                    "The search did NOT converge: %d evaluations (%d budget + %d "
                    "extension) did not meet its stopping rule (%s). Its best trial is "
                    "where the budget ended, not an answer. Raise max_iter or loosen "
                    "the tolerance; a re-run replays the trials already solved from "
                    "the cache.",
                    len(session.history),
                    budget,
                    session.extension,
                    session.stopping_rule,
                )
        finally:
            session.finished_at = time.time()
            reporter.close()
            close_optimizer = getattr(self.optimizer, "close", None)
            if callable(close_optimizer):
                close_optimizer()
        return session

    def _extension(self, budget: int, session: CalibrationSession) -> int:
        """Return what the engine is granted, once, when *budget* ends before its rule.

        Exactly the evaluations the engine reports it still needs, when it can
        count them and they fit in half the budget. Nothing otherwise.
        """
        remaining = getattr(self.optimizer, "evaluations_remaining", None)
        grant = remaining_grant(remaining, budget)
        if grant:
            logger.warning(
                "The search spent its budget of %d evaluations and needs %d more to "
                "meet its stopping rule (%s). Granting exactly those %d, once.",
                budget,
                grant,
                session.stopping_rule,
                grant,
            )
        elif isinstance(remaining, int) and remaining > 0:
            logger.warning(
                "The search spent its budget of %d evaluations and still needs %d to "
                "meet its stopping rule (%s), more than half its budget: nothing is "
                "granted.",
                budget,
                remaining,
                session.stopping_rule,
            )
        return grant

    def _run_until(
        self,
        budget: int,
        n_done: int,
        session: CalibrationSession,
        reporter: ProgressReporter | _NoopProgress,
    ) -> bool:
        """Ask and tell until *budget* is spent or the optimizer stops.

        Returns True when the optimizer ran out of suggestions: more budget
        would buy nothing, so no extension is granted then.
        """
        while n_done < budget:
            # A batch holds at least ``parallel`` trials: ``parallel`` alone must
            # run trials side by side, not wait for a batch_size set beside it.
            take = min(max(self.batch_size, self.parallel), budget - n_done)
            suggestions = self.optimizer.ask(n=take)
            if not suggestions:
                return True
            results = self._evaluate_batch(suggestions)
            for sugg, result in zip(suggestions, results, strict=True):
                session.history.append(result)
                reporter.update(sugg.trial_id, result)
                if self.on_iteration is not None:
                    self.on_iteration(sugg, result)
            self.optimizer.tell(results)
            # A method that labels its own progress knows the batch only now.
            refresh = getattr(reporter, "refresh", None)
            if callable(refresh):
                refresh()
            n_done += len(results)
            if self.optimizer.converged():
                return False
        return False

    def _judge_the_budget(self, budget: int) -> None:
        """Refuse a budget below the nominal count, announce one below the worst.

        Only an engine that counts its evaluations up front publishes
        ``counted_budget``; the root search does, from its bounds, sweep,
        tolerance and expansions. Refusing now costs nothing, refusing after the
        last solve costs the whole budget.
        """
        counted = getattr(self.optimizer, "counted_budget", None)
        if not isinstance(counted, CountedBudget):
            return
        verdict = short_budget(counted, budget)
        if verdict is None:
            return
        severity, message = verdict
        if severity == "error":
            raise OptimizerError(message)
        logger.warning(message)

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
