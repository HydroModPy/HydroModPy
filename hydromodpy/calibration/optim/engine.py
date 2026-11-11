"""CalibrationEngine - orchestrates an ask/tell loop.

The engine is solver-agnostic and pipeline-agnostic: it takes a callable
``evaluator(values: dict[str, float]) -> EvaluationResult`` and runs the
ask/tell loop until the optimizer converges or ``max_trials`` is reached.

``save_runs`` modes (implemented via ``promote_best_n``):

- ``"none"``  (default): each iteration is **only** a DuckDB row. No Zarr.
- ``"best_n"``: after the loop, promote the top ``save_best_n`` iterations
                into full simulations (caller-supplied promoter callable).
- ``"all"``:   each iteration is already a full simulation.

Running out of budget is not converging. The session says why the search
stopped in ``stop_state`` (:func:`hydromodpy.calibration.optim.stopping.
stop_state`): the engine met its own rule, exhausted the plan it counted up
front (the grid, the Latin hypercube), or spent its budget first. Only the
first two are ``converged``. An engine whose only rule is its budget spends it
by design: it has not converged, but there was no rule to miss, so the
session is ``settled`` and a staged calibration freezes its best, saying so.
An engine with a rule that spent its budget first is neither, and a staged
calibration freezes nothing from it.

An engine that can count its evaluations before the first solve publishes a
``counted_budget`` (:class:`~hydromodpy.calibration.optim.stopping.CountedBudget`).
The root search, the grid and the Latin hypercube do: ``max_trials = "auto"``
then runs the worst case, a declared budget below the nominal case is refused
before anything solves, one below the worst case of the root search is
announced, and a budget that still runs out is extended once by exactly the
``evaluations_remaining`` the engine reports, never by a fraction of the
budget. Every other engine gets no extension: re-running the same
file with a larger ``max_trials`` replays the trials already solved from the
params-hash cache. The cache key holds only what changes the cost of a
trial at given parameter values (the outputs, the blocks, the window and what the
evaluator reads), so ``max_trials``, ``precision``, ``seed``, ``method``,
``method_options`` and the bounds are all outside it. A search that changes one
still replays the trials it proposes at values already solved.
"""

from __future__ import annotations

import math
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from hydromodpy.calibration.optim.cache import ParamsHashCache, params_hash
from hydromodpy.calibration.optim.optimizer import (
    DEFAULT_ENGINE_TRAITS,
    EvaluationResult,
    Optimizer,
    ParamSuggestion,
)
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.optim.stopping import (
    CountedBudget,
    remaining_grant,
    resolve_budget,
    settled,
    short_budget,
    stop_state,
    stopping_rule,
)
from hydromodpy.catchment.stream_network.geometry import recharge_session
from hydromodpy.core.exceptions import OptimizerError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.runtime.interrupts import raise_if_stop_requested
from hydromodpy.results.record.checks import BUDGET_RULE, StopState, stop_text

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
    """The rule the engine stops on: its stopping option, its design, or ``"budget"``."""
    stop_state: StopState = "budget_spent"
    """Why the search stopped, set once the loop ends."""
    max_trials: int = 0
    """The budget the engine ran with, ``"auto"`` resolved, before any extension."""
    extension: int = 0
    """Evaluations granted beyond ``max_trials``: zero, or what a counting engine
    still needed when its budget ran out, once."""

    @property
    def converged(self) -> bool:
        """Whether the search met its own rule or exhausted its plan."""
        return self.stop_state != "budget_spent"

    @property
    def settled(self) -> bool:
        """Whether its answer may be built on (:func:`~hydromodpy.calibration.optim.stopping.settled`)."""
        return settled(self.stop_state, self.stopping_rule)

    @property
    def best(self) -> EvaluationResult | None:
        return self.optimizer.best()

    @property
    def duration_s(self) -> float:
        end = self.finished_at or time.time()
        return end - self.started_at


def _speculative_unused(result: EvaluationResult) -> bool:
    """Whether a speculative engine solved this result and did not read it."""
    metadata = getattr(result, "metadata", None) or {}
    return bool(metadata.get("speculative_unused"))


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
    max_trials: int | str = 100
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

    It always runs in the caller thread. In a parallel batch it runs as each trial
    ends, so a stop keeps the trials already finished. An engine that marks results
    after reading them (``marks_unread``) is called for the whole batch once it is told.
    """
    before_batch: Callable[[list[ParamSuggestion]], None] | None = None
    """Called with each batch, in the caller thread, before any trial of it runs.

    The suggestions come in the order the optimizer made them. A caller that
    numbers trials does it here, so the numbers follow that order and not the
    order in which parallel workers happen to start.
    """
    on_stop: Callable[[], None] | None = None
    """Called first when a parallel batch is stopped, before the engine waits for it.

    The workers of a pool are not on the terminal of the caller, so only this call
    reaches their solves. Without it a stop waits for the longest trial in flight.
    """
    stop_flag: Path | None = None
    """The stop flag of the session, ``<session>/.hmp/stop.json``, or ``None``.

    The engine reads it before each ``ask``, so a stop asked from outside ends the
    search between two batches of trials, the trials of the batch in flight
    finished and journaled. :class:`~hydromodpy.core.runtime.interrupts.StopRequested`
    leaves :meth:`run` as a ``KeyboardInterrupt`` does, and the session closes
    ``aborted`` like it does on a signal.
    """
    _live: bool = field(default=False, init=False, repr=False)
    """Whether the last batch was journaled trial by trial, as each one ended."""

    def run(self) -> CalibrationSession:
        sid = self.session_id or uuid.uuid4().hex
        reporter = self.progress or _NoopProgress()
        budget = resolve_budget(self.optimizer, self.max_trials)
        session = CalibrationSession(
            session_id=sid,
            optimizer=self.optimizer,
            space=self.space,
            started_at=time.time(),
            stopping_rule=stopping_rule(self.optimizer),
            max_trials=budget,
        )
        judged = session.stopping_rule != BUDGET_RULE
        # The trials of this session compare their mean recharge with each
        # other only, never with a build of another session or of a figure.
        with recharge_session(sid):
            try:
                if judged:
                    self._judge_the_budget(budget)
                ran_dry, n_done = self._run_until(budget, 0, session, reporter)
                if judged and not ran_dry and not self.optimizer.converged():
                    session.extension = self._extension(budget, session)
                    if session.extension:
                        _, n_done = self._run_until(
                            budget + session.extension, n_done, session, reporter
                        )
                session.stop_state = stop_state(
                    self.optimizer,
                    met=bool(self.optimizer.converged()),
                    spent=n_done >= budget + session.extension,
                )
                if session.converged:
                    logger.info(
                        "The search %s.", stop_text(session.stop_state, session.stopping_rule)
                    )
                elif not judged:
                    logger.warning(
                        "The search spent its budget of %d evaluations: it has no rule of its "
                        "own, so it did not converge, and its best trial is the best of a "
                        "budget-only search.",
                        n_done,
                    )
                else:
                    logger.warning(
                        "The search did NOT converge: %d evaluations (%d budget + %d "
                        "extension) did not meet its stopping rule (%s). Its best trial is "
                        "where the budget ended, not an answer. Raise max_trials: a re-run "
                        "of the same file replays the trials already solved from the "
                        "cache. So does a new precision, seed, method or method_options, "
                        "for every trial it proposes at values already solved.",
                        n_done,
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
    ) -> tuple[bool, int]:
        """Ask and tell until *budget* is spent or the optimizer stops.

        The stop flag is read before each ask, never inside a batch.

        Returns whether the optimizer ran out of suggestions, and the count of
        evaluations spent. Ran dry means more budget would buy nothing, so no
        extension is granted then. Only the evaluations the optimizer counts
        (:meth:`_counted`) spend the budget.
        """
        while n_done < budget:
            take = budget - n_done
            # A batch holds at least ``parallel`` trials: ``parallel`` alone must
            # run trials side by side, not wait for a batch_size set beside it. A
            # fixed plan is one queue instead: no point waits for another's result.
            traits = getattr(self.optimizer, "traits", DEFAULT_ENGINE_TRAITS)
            if self.parallel <= 1 or not traits.fixed_plan:
                take = min(max(self.batch_size, self.parallel), take)
            raise_if_stop_requested(self.stop_flag)
            suggestions = self.optimizer.ask(n=take)
            if not suggestions:
                return True, n_done
            results = self._evaluate_batch(suggestions, reporter)
            # Told first: a speculative engine marks the results it did not read
            # only then, and the journal row must carry that mark.
            self.optimizer.tell(results)
            for sugg, result in zip(suggestions, results, strict=True):
                session.history.append(result)
                if not self._live and not _speculative_unused(result):
                    reporter.update(sugg.trial_id, result)
                if self.on_iteration is not None and not self._live:
                    self.on_iteration(sugg, result)
            # A method that labels its own progress knows the batch only now.
            refresh = getattr(reporter, "refresh", None)
            if callable(refresh):
                refresh()
            n_done += self._counted(results)
            if self.optimizer.converged():
                return False, n_done
        return False, n_done

    def _counted(self, results: list[EvaluationResult]) -> int:
        """Return how many of the results just told spend the budget.

        Every result does, unless the optimizer says otherwise through an
        optional ``counted(results)``. A speculative engine solves candidates
        it may not read; those cost no budget, so a parallel run stops where
        the sequential one stops. They stay in the history all the same.
        """
        counted = getattr(self.optimizer, "counted", None)
        if callable(counted):
            return int(counted(results))
        return len(results)

    def _judge_the_budget(self, budget: int) -> None:
        """Refuse a budget below the nominal count, announce one below the worst.

        Only an engine that counts its evaluations up front publishes
        ``counted_budget``. The root search counts them from its bounds, sweep,
        precision and expansions, the grid and the Latin hypercube from their
        design. Refusing now costs nothing, refusing after the last solve costs
        the whole budget.
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
        reporter: ProgressReporter | _NoopProgress,
    ) -> list[EvaluationResult]:
        """Run every suggestion of one batch and return their results in order.

        ``parallel <= 1`` keeps the legacy sequential loop. ``parallel > 1``
        dispatches trials through a :class:`ThreadPoolExecutor`, one queue of
        ``parallel`` threads. With a prepared model the evaluator is a
        :class:`~hydromodpy.calibration.runners.worker_pool.TrialWorkerPool`, so
        the threads only wait on worker processes. Any other evaluator computes
        on them.
        """
        if self.before_batch is not None:
            self.before_batch(suggestions)
        self._live = False
        if self.parallel <= 1 or len(suggestions) <= 1:
            return [self._evaluate_with_cache(sugg) for sugg in suggestions]
        workers = min(self.parallel, len(suggestions))
        # ContextVars do NOT cross the thread boundary, so give each worker its own
        # copy of THIS thread's context. copy_context() runs here, in the caller
        # thread, so every copy inherits the current bindings; a fresh copy per task
        # avoids entering one Context object from several threads at once.
        tasks = [(copy_context(), sugg) for sugg in suggestions]

        def _run_in_context(item: tuple) -> EvaluationResult:
            ctx, sugg = item
            return ctx.run(self._evaluate_with_cache, sugg)

        # An engine that marks the results it did not read, after the batch is told,
        # reports and journals then: a line written before that mark would count a
        # trial the search never read.
        self._live = not getattr(self.optimizer, "marks_unread", False)
        results: list[EvaluationResult | None] = [None] * len(suggestions)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_run_in_context, task): i for i, task in enumerate(tasks)}
            try:
                for future in as_completed(futures):
                    i = futures[future]
                    results[i] = future.result()
                    if self._live:
                        reporter.update(suggestions[i].trial_id, results[i])
                        if self.on_iteration is not None:
                            self.on_iteration(suggestions[i], results[i])
            except BaseException:
                # A stop must not wait for the trials in flight, nor for the queued
                # ones, nor start them.
                if self.on_stop is not None:
                    self.on_stop()
                pool.shutdown(wait=True, cancel_futures=True)
                raise
        return results

    def _evaluate_with_cache(self, sugg: ParamSuggestion) -> EvaluationResult:
        if self.cache is None:
            return self._with_parameter_metadata(self.evaluator(sugg), sugg)
        key = params_hash(sugg.values, context=self.cache_context)
        hit = self.cache.get(key)
        if hit is not None:
            return EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=None,
                cost=hit.cost,
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
        if result.status == "completed" and math.isfinite(result.cost):
            self.cache.put(
                key,
                cost=result.cost,
                components=result.components,
            )
        # Enrich metadata with hash for persistence.
        meta = dict(result.metadata or {})
        meta.setdefault("params_hash", key)
        meta.setdefault("parameters", self.space.describe_values(sugg.values))
        return replace(result, metadata=meta)

    def _with_parameter_metadata(
        self,
        result: EvaluationResult,
        sugg: ParamSuggestion,
    ) -> EvaluationResult:
        meta = dict(result.metadata or {})
        meta.setdefault("parameters", self.space.describe_values(sugg.values))
        # Recorded without a cache too, so a resumed session can still check
        # that one cost scored every trial of its journal.
        if self.cache_context is not None:
            meta.setdefault("params_hash", params_hash(sugg.values, context=self.cache_context))
        return replace(result, metadata=meta)


__all__ = [
    "CalibrationEngine",
    "CalibrationSession",
    "EvaluatorFn",
]
