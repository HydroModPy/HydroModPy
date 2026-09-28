"""SciPy optimizer adapter.

Exposes scipy.optimize methods behind the ask/tell Protocol.

Supported methods:
    - ``"scipy_de"`` → scipy.optimize.differential_evolution. SciPy's API is
      push-based (it calls the objective), so it runs in a thread behind a
      queue: ``ask()`` pops the next candidate SciPy wants evaluated,
      ``tell()`` feeds the objective value back.
    - ``"scipy_nelder_mead"`` → scipy.optimize.minimize(method="Nelder-Mead"),
      reproduced call for call by :mod:`hydromodpy.calibration.optim.nelder_mead`
      so that one step's candidates can be solved side by side.
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable, MutableMapping
from typing import Any

import numpy as np

from hydromodpy.calibration.optim.nelder_mead import CandidateKey, SpeculativeNelderMead
from hydromodpy.calibration.optim.optimizer import (
    FAILED_EVAL_COST,
    EngineTraits,
    EvaluationResult,
    ParamSuggestion,
    register_optimizer,
)
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.optim.prior_sampling import (
    transformed_prior_center,
    transformed_prior_samples,
)
from hydromodpy.core.exceptions import OptimizerError


class _BridgeClosed(RuntimeError):
    """Internal signal used to stop a background SciPy worker."""


_SENTINEL = object()
_BRIDGE_EMPTY = object()


class _AskTellBridge:
    """Bridges SciPy's push-style API to an ask/tell pull-style API.

    SciPy runs the optimization in a background thread, pushing candidate
    vectors via ``_obj``. Calls to ``ask`` pop from ``out_q`` (blocking),
    calls to ``tell`` push into ``in_q``.
    """

    def __init__(self, method: Callable[[Callable], object]):
        self._method = method
        self._in_q: queue.Queue[float | object] = queue.Queue()
        self._out_q: queue.Queue[np.ndarray | None] = queue.Queue()
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._result: object | None = None
        self._thread.start()

    def _obj(self, x: np.ndarray) -> float:
        if self._done.is_set():
            raise _BridgeClosed
        self._out_q.put(np.array(x, dtype=float))
        value = self._in_q.get()
        if value is _SENTINEL:
            raise _BridgeClosed
        return float(value)

    def _worker(self) -> None:
        try:
            self._result = self._method(self._obj)
        except _BridgeClosed:
            self._result = None
        finally:
            self._done.set()
            self._out_q.put(None)

    def next_point(self, timeout: float | None = None) -> np.ndarray | None:
        """Block until SciPy requests the next evaluation (or finishes)."""
        return self._out_q.get(timeout=timeout)

    def next_point_nowait(self) -> np.ndarray | None | object:
        """Return a queued point, or ``_BRIDGE_EMPTY`` when none is ready yet."""
        try:
            return self._out_q.get_nowait()
        except queue.Empty:
            return _BRIDGE_EMPTY

    def feed(self, value: float) -> None:
        self._in_q.put(value)

    def finished(self) -> bool:
        return self._done.is_set()

    def succeeded(self) -> bool:
        """Whether SciPy ended and says its own stopping rule was met.

        ``OptimizeResult.success`` is False when SciPy stopped on its own
        ``maxiter`` or ``maxfev``: the thread ended, the search did not converge.
        A bridge closed from outside carries no result and has not succeeded.
        """
        return self._done.is_set() and bool(getattr(self._result, "success", False))

    def close(self) -> None:
        self._done.set()
        self._in_q.put(_SENTINEL)
        self._out_q.put(None)
        self._thread.join(timeout=1.0)


class _ScipyAdapterBase:
    name = "scipy"

    traits = EngineTraits(supports_parallel=False)
    """Sequential by construction: SciPy runs with ``workers=1``, so the next
    point exists only once the current one has been told back. Asking for
    concurrent trials buys nothing here, and the ``ask`` above says so in its own
    comment."""

    def __init__(self, space: ParameterSpace, *, seed: int | None = None):
        self.space = space
        self._seed = seed
        self._history: list[EvaluationResult] = []
        self._pending: list[tuple[int, np.ndarray]] = []
        self._trial_id = 0
        self._bridge = _AskTellBridge(self._make_method())

    def _make_method(self) -> Callable[[Callable], object]:
        raise NotImplementedError

    def _bounds_transformed(self) -> list[tuple[float, float]]:
        return [(p.lower_transformed, p.upper_transformed) for p in self.space.parameters]

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for slot in range(n):
            if slot == 0:
                point = self._bridge.next_point()
            else:
                # SciPy DE is sequential (workers=1): the next point is only
                # produced after the current one is told back.
                # Never block here, or ask(n>1) would deadlock; return only the
                # points already queued (typically one).
                point = self._bridge.next_point_nowait()
                if point is _BRIDGE_EMPTY:
                    break
            if point is None:
                break
            self._trial_id += 1
            values = {
                p.name: p.to_physical(float(point[i])) for i, p in enumerate(self.space.parameters)
            }
            self._pending.append((self._trial_id, point))
            out.append(ParamSuggestion(trial_id=self._trial_id, values=values, source="ask"))
        return out

    def suggest_next(self) -> ParamSuggestion:
        got = self.ask(1)
        if not got:
            raise StopIteration("scipy optimizer finished")
        return got[0]

    def tell(self, results: list[EvaluationResult]) -> None:
        for r in results:
            # Pop matching pending point (FIFO match by trial_id)
            for i, (tid, _pt) in enumerate(self._pending):
                if tid == r.trial_id:
                    self._pending.pop(i)
                    break
            value = r.objective_value
            if r.status != "completed" or not np.isfinite(value):
                value = FAILED_EVAL_COST
            self._bridge.feed(float(value))
            self._history.append(r)

    def best(self) -> EvaluationResult | None:
        valid = [r for r in self._history if r.status == "completed"]
        if not valid:
            return None
        return min(valid, key=lambda r: r.objective_value)

    def converged(self) -> bool:
        """Whether SciPy ended on its own tolerance, not on its own evaluation cap."""
        return self._bridge.succeeded() and not self._pending

    def close(self) -> None:
        self._bridge.close()


@register_optimizer("scipy_de")
class ScipyDE(_ScipyAdapterBase):
    """scipy.optimize.differential_evolution adapter."""

    name = "scipy_de"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        seed: int | None = None,
        maxiter: int = 100,
        popsize: int = 15,
        tol: float = 0.01,
    ):
        self._maxiter = maxiter
        self._popsize = popsize
        self._tol = tol
        super().__init__(space, seed=seed)

    def _make_method(self) -> Callable[[Callable], object]:
        from scipy.optimize import differential_evolution

        bounds = self._bounds_transformed()
        rng = np.random.default_rng(self._seed)
        init = transformed_prior_samples(
            self.space,
            rng,
            max(5, self._popsize * max(1, self.space.dim)),
        )

        def run(obj: Callable[[np.ndarray], float]) -> object:
            return differential_evolution(
                obj,
                bounds=bounds,
                seed=self._seed,
                maxiter=self._maxiter,
                popsize=self._popsize,
                tol=self._tol,
                polish=False,
                init=init,
            )

        return run


@register_optimizer("scipy_nelder_mead")
class ScipyNelderMead:
    """Nelder-Mead simplex that reproduces scipy.optimize.minimize(method='Nelder-Mead').

    The simplex is SciPy's algorithm, ported call for call in
    :mod:`hydromodpy.calibration.optim.nelder_mead`, run with ``adaptive=True``,
    a bound-scaled initial simplex and an objective clipped to the bounds.

    ``ask(1)`` hands out the points SciPy would evaluate, in SciPy's order.
    ``ask(n)`` adds the other candidates of the same step, so ``parallel``
    solves them side by side. The simplex reads only the values SciPy would
    have read: the path, the best trial and the stopping point are the
    sequential ones whatever the width. A trial it did not read is marked
    ``speculative_unused`` in its metadata and does not count toward the budget
    (:meth:`counted`).
    """

    # scipy's xatol is an absolute width in the variable the simplex walks, which
    # is the transformed one here.
    traits = EngineTraits(
        supports_parallel=True,
        accepts_a_start_point=True,
        tolerance_option="xatol",
        tolerance_reads="search_width",
    )

    name = "scipy_nelder_mead"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        seed: int | None = None,
        maxiter: int | None = None,
        maxfev: int | None = None,
        xatol: float | None = None,
        fatol: float | None = None,
        start_at: Any | None = None,
    ):
        self.space = space
        self._seed = seed
        self._maxiter = 100 if maxiter is None else int(maxiter)
        self._maxfev = self._maxiter if maxfev is None else int(maxfev)
        self._xatol = None if xatol is None else float(xatol)
        self._fatol = None if fatol is None else float(fatol)
        self._start_at = None if start_at is None else np.asarray(start_at, dtype=float).ravel()
        bounds = [(p.lower_transformed, p.upper_transformed) for p in space.parameters]
        self._lower = np.array([b[0] for b in bounds], dtype=float)
        self._upper = np.array([b[1] for b in bounds], dtype=float)
        self._simplex = self._make_simplex()
        self._trial_id = 0
        self._pending: dict[int, CandidateKey] = {}
        self._told: dict[CandidateKey, EvaluationResult] = {}
        self._used: list[EvaluationResult] = []
        self._counted = 0

    def _initial_point(self, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
        """Return where the simplex is built, the prior centre unless told otherwise.

        A caller states a start when it is repeating the search on purpose: the
        simplex is deterministic, so the same start returns the same answer and a
        spread read off identical runs would be zero by construction.
        """
        if self._start_at is None:
            return transformed_prior_center(self.space)
        if self._start_at.size != lower.size:
            raise OptimizerError(
                f"start_at carries {self._start_at.size} value(s) and the space declares "
                f"{lower.size}; a start point is one coordinate per calibrated parameter, "
                "in transformed space."
            )
        return np.clip(self._start_at, lower, upper)

    def _make_simplex(self) -> SpeculativeNelderMead:
        lower, upper = self._lower, self._upper
        x0 = self._initial_point(lower, upper)
        # Bound-scaled initial simplex (10 % of range per axis) gives
        # Nelder-Mead a wider starting spread than scipy's 5 %-of-x0
        # default, reducing the iter count needed to reach a tight
        # tolerance on tight log-scale parameters.
        n = x0.size
        delta = 0.1 * (upper - lower)
        initial_simplex = np.tile(x0, (n + 1, 1))
        for i in range(n):
            initial_simplex[i + 1, i] = float(np.clip(x0[i] + delta[i], lower[i], upper[i]))
        tolerances: dict[str, float] = {}
        if self._xatol is not None:
            tolerances["xatol"] = self._xatol
        if self._fatol is not None:
            tolerances["fatol"] = self._fatol
        return SpeculativeNelderMead(
            x0,
            initial_simplex=initial_simplex,
            maxiter=self._maxiter,
            maxfev=self._maxfev,
            adaptive=True,
            **tolerances,
        )

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for proposal in self._simplex.propose(n):
            self._trial_id += 1
            point = np.clip(np.asarray(proposal.point, dtype=float), self._lower, self._upper)
            values = {
                p.name: p.to_physical(float(point[i])) for i, p in enumerate(self.space.parameters)
            }
            self._pending[self._trial_id] = proposal.key
            out.append(ParamSuggestion(trial_id=self._trial_id, values=values, source="ask"))
        return out

    def suggest_next(self) -> ParamSuggestion:
        got = self.ask(1)
        if not got:
            raise StopIteration("scipy optimizer finished")
        return got[0]

    def tell(self, results: list[EvaluationResult]) -> None:
        read_before = len(self._simplex.used)
        for r in results:
            key = self._pending.pop(r.trial_id, None)
            if key is None:
                if not self._pending:
                    continue
                # A result that names no pending trial answers the oldest one,
                # as the SciPy bridge this replaces read its values in order.
                key = self._pending.pop(next(iter(self._pending)))
            value = r.objective_value
            if r.status != "completed" or not np.isfinite(value):
                value = FAILED_EVAL_COST
            self._told[key] = r
            self._simplex.receive(key, float(value))
        read_now = self._simplex.used[read_before:]
        self._used.extend(self._told.pop(call.key) for call in read_now)
        self._counted = len(read_now)
        for key in [k for k in self._told if self._simplex.fate(k) == "unused"]:
            metadata = self._told.pop(key).metadata
            if isinstance(metadata, MutableMapping):
                metadata["speculative_unused"] = True

    def counted(self, results: list[EvaluationResult]) -> int:
        """Return how many evaluations the last ``tell`` spent from the budget.

        Only the ones the simplex read count. A speculative candidate it never
        read was solved for nothing and costs no budget, so a parallel run stops
        where the sequential one stops.
        """
        return self._counted

    def best(self) -> EvaluationResult | None:
        """Return the lowest completed evaluation the simplex read."""
        valid = [r for r in self._used if r.status == "completed"]
        if not valid:
            return None
        return min(valid, key=lambda r: r.objective_value)

    def converged(self) -> bool:
        """Whether SciPy's run would end with ``success``: its tolerance, not a cap."""
        result = self._simplex.result
        return result is not None and result.success

    def close(self) -> None:
        self._simplex.close()


__all__ = ["ScipyDE", "ScipyNelderMead"]
