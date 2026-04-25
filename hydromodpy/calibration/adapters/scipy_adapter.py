"""SciPy optimizer adapter.

Exposes scipy.optimize methods behind the ask/tell Protocol. SciPy's API is
push-based (it calls the objective), so we drive it as a generator via a
queue: ``ask()`` pops the next candidate SciPy wants evaluated, ``tell()``
feeds the objective value back.

Supported methods:
    - ``"scipy_de"`` → scipy.optimize.differential_evolution
    - ``"scipy_nelder_mead"`` → scipy.optimize.minimize(method="Nelder-Mead")
"""

from __future__ import annotations

import queue
import threading
from collections.abc import Callable

import numpy as np

from hydromodpy.calibration.optimizer import (
    FAILED_EVAL_COST,
    EvaluationResult,
    ParamSuggestion,
    register_optimizer,
)
from hydromodpy.calibration.parameters import ParameterSpace


class _AskTellBridge:
    """Bridges SciPy's push-style API to an ask/tell pull-style API.

    SciPy runs the optimization in a background thread, pushing candidate
    vectors via ``_obj``. Calls to ``ask`` pop from ``out_q`` (blocking),
    calls to ``tell`` push into ``in_q``.
    """

    def __init__(self, method: Callable[[Callable], object]):
        self._method = method
        self._in_q: queue.Queue[float] = queue.Queue()
        self._out_q: queue.Queue[np.ndarray | None] = queue.Queue()
        self._done = threading.Event()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._result: object | None = None
        self._thread.start()

    def _obj(self, x: np.ndarray) -> float:
        self._out_q.put(np.array(x, dtype=float))
        return self._in_q.get()

    def _worker(self) -> None:
        try:
            self._result = self._method(self._obj)
        finally:
            self._done.set()
            self._out_q.put(None)

    def next_point(self, timeout: float | None = None) -> np.ndarray | None:
        """Block until SciPy requests the next evaluation (or finishes)."""
        return self._out_q.get(timeout=timeout)

    def feed(self, value: float) -> None:
        self._in_q.put(value)

    def finished(self) -> bool:
        return self._done.is_set()


class _ScipyAdapterBase:
    name = "scipy"

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
        for _ in range(n):
            point = self._bridge.next_point()
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
        return self._bridge.finished() and not self._pending


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

        def run(obj: Callable[[np.ndarray], float]) -> object:
            return differential_evolution(
                obj,
                bounds=bounds,
                seed=self._seed,
                maxiter=self._maxiter,
                popsize=self._popsize,
                tol=self._tol,
                polish=False,
            )

        return run


@register_optimizer("scipy_nelder_mead")
@register_optimizer("nelder_mead")
@register_optimizer("simplex")
class ScipyNelderMead(_ScipyAdapterBase):
    """scipy.optimize.minimize(method='Nelder-Mead') adapter.

    Registered under ``scipy_nelder_mead`` (default), ``nelder_mead`` and
    ``simplex`` (legacy aliases). Accepts ``max_iter`` / ``max_fun`` as
    synonyms of ``maxiter`` / ``maxfev`` and ``xtol`` / ``ftol`` as
    synonyms of ``xatol`` / ``fatol`` for parity with the legacy driver.
    """

    name = "scipy_nelder_mead"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        seed: int | None = None,
        maxiter: int | None = None,
        max_iter: int | None = None,
        max_fun: int | None = None,
        xatol: float | None = None,
        xtol: float | None = None,
        fatol: float | None = None,
        ftol: float | None = None,
    ):
        resolved_maxiter = max_iter if max_iter is not None else maxiter
        if resolved_maxiter is None:
            resolved_maxiter = 100
        self._maxiter = int(resolved_maxiter)
        self._maxfev = int(max_fun) if max_fun is not None else self._maxiter
        resolved_xatol = xatol if xatol is not None else xtol
        resolved_fatol = fatol if fatol is not None else ftol
        self._xatol = float(resolved_xatol) if resolved_xatol is not None else 1e-4
        self._fatol = float(resolved_fatol) if resolved_fatol is not None else 1e-4
        super().__init__(space, seed=seed)

    def _make_method(self) -> Callable[[Callable], object]:
        from scipy.optimize import minimize

        bounds = self._bounds_transformed()
        lower = np.array([b[0] for b in bounds], dtype=float)
        upper = np.array([b[1] for b in bounds], dtype=float)
        x0 = 0.5 * (lower + upper)
        # Bound-scaled initial simplex (10 % of range per axis) gives
        # Nelder-Mead a wider starting spread than scipy's 5 %-of-x0
        # default, reducing the iter count needed to reach a tight
        # tolerance on tight log-scale parameters.
        n = x0.size
        delta = 0.1 * (upper - lower)
        initial_simplex = np.tile(x0, (n + 1, 1))
        for i in range(n):
            initial_simplex[i + 1, i] = float(np.clip(x0[i] + delta[i], lower[i], upper[i]))

        def run(obj: Callable[[np.ndarray], float]) -> object:
            def clipped(x: np.ndarray) -> float:
                return obj(np.clip(np.asarray(x, dtype=float), lower, upper))

            return minimize(
                clipped,
                x0,
                method="Nelder-Mead",
                options={
                    "maxiter": self._maxiter,
                    "maxfev": self._maxfev,
                    "xatol": self._xatol,
                    "fatol": self._fatol,
                    "adaptive": True,
                    "initial_simplex": initial_simplex,
                },
            )

        return run


__all__ = ["ScipyDE", "ScipyNelderMead"]
