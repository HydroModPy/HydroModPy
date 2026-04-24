"""CMA-ES optimizer adapter backed by the `cma` package.

Matches the numeric behaviour of the legacy ``_driver_cma_es`` (see
``hydromodpy/calibration/benchmark.py``). The adapter runs the CMA-ES
search in the transformed parameter space exposed by
:class:`~hydromodpy.calibration.parameters.ParameterSpace` and optionally
normalises the search domain into the unit cube.

Driven via the engine's ask/tell loop, the adapter keeps a background
thread running the push-style ``cma.CMAEvolutionStrategy.ask`` /
``tell`` calls and exposes them as a pull-style queue, mirroring the
pattern used by :mod:`hydromodpy.calibration.adapters.scipy_adapter`.
"""

from __future__ import annotations

import math
import queue
import threading

import numpy as np

from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    register_optimizer,
)
from hydromodpy.calibration.parameters import ParameterSpace


@register_optimizer("cma_es")
class CmaEsAdapter:
    """Adapter for the ``cma`` package's CMA-ES strategy.

    Parameters
    ----------
    space
        The transformed parameter space.
    sigma0
        Initial step size. Default ``0.25`` (matches legacy).
    popsize
        Population size. Default ``6`` (matches legacy).
    max_evaluations
        Evaluation budget. Default ``30`` (matches legacy).
    normalize
        When ``True`` (default), rescale bounds to the unit cube before
        driving CMA-ES. Required to keep the legacy numeric behaviour.
    seed
        RNG seed forwarded to ``cma``.
    """

    name = "cma_es"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        sigma0: float = 0.25,
        popsize: int = 6,
        max_evaluations: int = 30,
        normalize: bool = True,
        seed: int | None = None,
    ) -> None:
        try:
            import cma  # noqa: F401  # surfaced only when the adapter is instantiated
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "The 'cma' package is required for the cma_es method; "
                "install via 'pip install cma'."
            ) from exc

        self.space = space
        self._sigma0 = float(sigma0)
        self._popsize = int(popsize)
        self._max_evaluations = int(max_evaluations)
        self._normalize = bool(normalize)
        self._seed = None if seed is None else int(seed)

        self._lower = np.asarray([p.lower_transformed for p in space.parameters], dtype=float)
        self._upper = np.asarray([p.upper_transformed for p in space.parameters], dtype=float)

        self._in_q: queue.Queue[float | object] = queue.Queue()
        self._out_q: queue.Queue[np.ndarray | None] = queue.Queue()
        self._done = threading.Event()
        self._history: list[EvaluationResult] = []
        self._pending: list[tuple[int, np.ndarray]] = []
        self._trial_id = 0
        self._n_eval = 0
        self._best: tuple[float, np.ndarray] | None = None
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # Background worker
    # ------------------------------------------------------------------

    def _to_physical(self, x: np.ndarray) -> np.ndarray:
        """Return the physical-space vector for a CMA-ES candidate."""
        arr = np.asarray(x, dtype=float)
        if self._normalize:
            span = self._upper - self._lower
            span = np.where(span > 0.0, span, 1.0)
            clipped = np.clip(arr, 0.0, 1.0)
            return self._lower + clipped * span
        return np.clip(arr, self._lower, self._upper)

    def _worker(self) -> None:
        import cma

        if self._normalize:
            span = self._upper - self._lower
            span = np.where(span > 0.0, span, 1.0)
            x0_t = (0.5 * (self._lower + self._upper) - self._lower) / span
            bounds = [np.zeros_like(self._lower).tolist(), np.ones_like(self._upper).tolist()]
            x0 = x0_t
        else:
            bounds = [self._lower.tolist(), self._upper.tolist()]
            x0 = 0.5 * (self._lower + self._upper)

        options: dict[str, object] = {
            "popsize": self._popsize,
            "maxfevals": self._max_evaluations,
            "bounds": bounds,
            "verbose": -9,
        }
        if self._seed is not None:
            options["seed"] = self._seed

        try:
            es = cma.CMAEvolutionStrategy(list(x0), self._sigma0, options)
            while not es.stop() and self._n_eval < self._max_evaluations:
                xs = es.ask()
                costs: list[float] = []
                for x in xs:
                    if self._n_eval >= self._max_evaluations:
                        break
                    self._out_q.put(np.asarray(x, dtype=float))
                    cost = self._in_q.get()
                    if cost is _STOP:
                        return
                    costs.append(float(cost))
                if costs:
                    es.tell(xs[: len(costs)], costs)
        finally:
            self._done.set()
            self._out_q.put(None)

    # ------------------------------------------------------------------
    # Ask / tell
    # ------------------------------------------------------------------

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            point = self._out_q.get()
            if point is None:
                break
            self._trial_id += 1
            physical = self._to_physical(point)
            values = {
                p.name: p.to_physical(float(physical[i]))
                for i, p in enumerate(self.space.parameters)
            }
            self._pending.append((self._trial_id, physical))
            out.append(ParamSuggestion(trial_id=self._trial_id, values=values, source="ask"))
        return out

    def suggest_next(self) -> ParamSuggestion:
        got = self.ask(1)
        if not got:
            raise StopIteration("cma_es evaluation budget exhausted")
        return got[0]

    def tell(self, results: list[EvaluationResult]) -> None:
        for r in results:
            for i, (tid, _pt) in enumerate(self._pending):
                if tid == r.trial_id:
                    _, physical = self._pending.pop(i)
                    break
            else:
                continue
            value = r.objective_value
            if r.status != "completed" or not math.isfinite(value):
                value = 1e12
            self._in_q.put(float(value))
            self._n_eval += 1
            self._history.append(r)
            if r.status == "completed" and math.isfinite(value):
                if self._best is None or value < self._best[0]:
                    self._best = (float(value), physical.copy())

    def best(self) -> EvaluationResult | None:
        valid = [r for r in self._history if r.status == "completed"]
        if not valid:
            return None
        return min(valid, key=lambda r: r.objective_value)

    def converged(self) -> bool:
        return self._done.is_set() and not self._pending


_STOP: object = object()


__all__ = ["CmaEsAdapter"]
