"""CMA-ES optimizer adapter backed by the `cma` package.

Matches the numeric behaviour of the legacy ``_driver_cma_es`` (see
``hydromodpy/calibration/benchmark.py``). The adapter runs the CMA-ES
search in the transformed parameter space exposed by
:class:`~hydromodpy.calibration.parameters.ParameterSpace` and optionally
normalises the search domain into the unit cube.

The ask/tell contract:

- ``ask(n)`` returns up to ``n`` points from the current CMA-ES batch
  (next batch is drawn lazily when the previous one is fully scored).
- ``tell(results)`` writes costs into the current-batch slot; once every
  slot is filled, the adapter feeds the batch back to CMA and resets.

This matches the exact legacy order: CMA generates ``popsize`` points,
all points are scored, CMA updates, repeat.
"""

from __future__ import annotations

import math

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
            import cma
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

        self._lower = np.asarray([p.lower_transformed for p in space.parameters], dtype=float)
        self._upper = np.asarray([p.upper_transformed for p in space.parameters], dtype=float)

        if self._normalize:
            span = self._upper - self._lower
            span = np.where(span > 0.0, span, 1.0)
            self._span = span
            x0_t = (0.5 * (self._lower + self._upper) - self._lower) / span
            bounds = [
                np.zeros_like(self._lower).tolist(),
                np.ones_like(self._upper).tolist(),
            ]
            x0 = list(x0_t)
        else:
            self._span = np.ones_like(self._upper)
            bounds = [self._lower.tolist(), self._upper.tolist()]
            x0 = list(0.5 * (self._lower + self._upper))

        options: dict[str, object] = {
            "popsize": self._popsize,
            "maxfevals": self._max_evaluations,
            "bounds": bounds,
            "verbose": -9,
        }
        if seed is not None:
            options["seed"] = int(seed)

        self._es = cma.CMAEvolutionStrategy(x0, self._sigma0, options)
        self._history: list[EvaluationResult] = []
        self._trial_id = 0
        self._n_eval = 0
        self._best_trial_id: int | None = None
        self._best_cost = float("inf")

        self._batch_xs: list[np.ndarray] = []
        self._batch_trial_ids: list[int] = []
        self._batch_costs: list[float | None] = []
        self._done = False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _to_physical(self, x: np.ndarray) -> np.ndarray:
        arr = np.asarray(x, dtype=float)
        if self._normalize:
            clipped = np.clip(arr, 0.0, 1.0)
            return self._lower + clipped * self._span
        return np.clip(arr, self._lower, self._upper)

    def _draw_batch_if_needed(self) -> None:
        if self._batch_xs and None in self._batch_costs:
            return  # current batch still needs telling
        if self._done:
            return
        if self._es.stop() or self._n_eval >= self._max_evaluations:
            self._done = True
            return
        xs = self._es.ask()
        self._batch_xs = [np.asarray(x, dtype=float) for x in xs]
        self._batch_trial_ids = []
        self._batch_costs = [None] * len(self._batch_xs)

    # ------------------------------------------------------------------
    # Ask / tell
    # ------------------------------------------------------------------

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            self._draw_batch_if_needed()
            if self._done:
                break
            next_slot = len(self._batch_trial_ids)
            if next_slot >= len(self._batch_xs):
                # Should never happen: all asked but not all told yet.
                break
            x = self._batch_xs[next_slot]
            self._trial_id += 1
            physical = self._to_physical(x)
            values = {
                p.name: p.to_physical(float(physical[i]))
                for i, p in enumerate(self.space.parameters)
            }
            self._batch_trial_ids.append(self._trial_id)
            out.append(ParamSuggestion(trial_id=self._trial_id, values=values, source="ask"))
            if self._n_eval + len(self._batch_trial_ids) >= self._max_evaluations:
                # Stop enlarging this batch once budget runs out.
                pass
        return out

    def suggest_next(self) -> ParamSuggestion:
        got = self.ask(1)
        if not got:
            raise StopIteration("cma_es evaluation budget exhausted")
        return got[0]

    def tell(self, results: list[EvaluationResult]) -> None:
        for r in results:
            if r.trial_id not in self._batch_trial_ids:
                continue
            idx = self._batch_trial_ids.index(r.trial_id)
            value = r.objective_value
            cost = float(value) if (r.status == "completed" and math.isfinite(value)) else 1e12
            self._batch_costs[idx] = cost
            self._n_eval += 1
            self._history.append(r)
            if r.status == "completed" and math.isfinite(value):
                if value < self._best_cost:
                    self._best_cost = float(value)
                    self._best_trial_id = r.trial_id

        # When the current batch is fully scored, feed CMA and reset.
        if (
            self._batch_xs
            and len(self._batch_trial_ids) == len(self._batch_xs)
            and None not in self._batch_costs
        ):
            self._es.tell(self._batch_xs, list(self._batch_costs))
            self._batch_xs = []
            self._batch_trial_ids = []
            self._batch_costs = []
            if self._es.stop() or self._n_eval >= self._max_evaluations:
                self._done = True

    def best(self) -> EvaluationResult | None:
        valid = [r for r in self._history if r.status == "completed"]
        if not valid:
            return None
        return min(valid, key=lambda r: r.objective_value)

    def converged(self) -> bool:
        return self._done


__all__ = ["CmaEsAdapter"]
