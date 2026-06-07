"""CMA-ES optimizer adapter backed by the `cma` package.

The adapter runs the CMA-ES search in the transformed parameter space exposed by
:class:`~hydromodpy.calibration.parameters.ParameterSpace` and optionally
normalises the search domain into the unit cube.

The ask/tell contract:

- ``ask(n)`` returns up to ``n`` points from the current CMA-ES batch
  (next batch is drawn lazily when the previous one is fully scored).
- ``tell(results)`` writes costs into the current-batch slot; once every
  slot is filled, the adapter feeds the batch back to CMA and resets.

CMA generates ``popsize`` points, all points are scored, CMA updates, repeat.
"""

from __future__ import annotations

import math

import numpy as np

from hydromodpy.calibration.adapters._prior_sampling import transformed_prior_center
from hydromodpy.calibration.optimizer import (
    FAILED_EVAL_COST,
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
        Initial step size.
    popsize
        Population size.
    max_evaluations
        Evaluation budget.
    normalize
        When ``True`` (default), rescale bounds to the unit cube before
        driving CMA-ES.
    seed
        RNG seed forwarded to ``cma``.
    restarts
        Number of CMA-ES restarts. ``0`` (default) keeps the single-strategy
        behaviour. When ``> 0``, each time the underlying CMA strategy stops
        before the evaluation budget is exhausted the adapter re-instantiates
        a fresh ``CMAEvolutionStrategy`` from a perturbed ``x0`` (uniform
        offset within +/- ``0.1`` in transformed space, clipped to bounds)
        and continues consuming the remaining budget. The total number of
        full-model evaluations stays capped by ``max_evaluations``.
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
        restarts: int = 0,
    ) -> None:
        try:
            import cma
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise ImportError(
                "The 'cma' package is required for the cma_es method; "
                "install via 'pip install cma'."
            ) from exc

        self.space = space
        self._cma_module = cma
        self._sigma0 = float(sigma0)
        self._popsize = int(popsize)
        self._max_evaluations = int(max_evaluations)
        self._normalize = bool(normalize)
        self._restarts = max(0, int(restarts))
        self._restarts_used = 0
        self._seed = None if seed is None else int(seed)
        self._restart_rng = np.random.default_rng(self._seed)

        self._lower = np.asarray([p.lower_transformed for p in space.parameters], dtype=float)
        self._upper = np.asarray([p.upper_transformed for p in space.parameters], dtype=float)
        center = transformed_prior_center(space)

        if self._normalize:
            span = self._upper - self._lower
            span = np.where(span > 0.0, span, 1.0)
            self._span = span
            self._x0_t = (center - self._lower) / span
            self._bounds_t = [
                np.zeros_like(self._lower).tolist(),
                np.ones_like(self._upper).tolist(),
            ]
            self._lower_t = np.zeros_like(self._lower)
            self._upper_t = np.ones_like(self._upper)
        else:
            self._span = np.ones_like(self._upper)
            self._x0_t = center
            self._bounds_t = [self._lower.tolist(), self._upper.tolist()]
            self._lower_t = self._lower
            self._upper_t = self._upper

        self._es = self._make_strategy(self._x0_t)
        self._history: list[EvaluationResult] = []
        self._trial_id = 0
        self._n_eval = 0
        self._best_trial_id: int | None = None
        self._best_cost = float("inf")

        self._batch_xs: list[np.ndarray] = []
        self._batch_trial_ids: list[int] = []
        self._batch_costs: list[float | None] = []
        self._done = False

    def _make_strategy(self, x0_t: np.ndarray):
        options: dict[str, object] = {
            "popsize": self._popsize,
            "maxfevals": self._max_evaluations,
            "bounds": self._bounds_t,
            "verbose": -9,
            # Disable convergence criteria that cause premature stops or
            # internal cma library failures (``set_i`` "dimension needed")
            # on tiny 1-D problems so the evaluation budget is the only stop.
            "tolx": 1e-20,
            "tolfun": 1e-20,
            "tolfacupx": 1e20,
            "tolflatfitness": self._max_evaluations,
            # Disable the implicit maxstd-from-bounds behaviour that fires
            # the ``_stds_into_limits`` path on 1-D bounded problems and
            # raises ``set_i`` "dimension needed" before sigma_vec has
            # been lazily initialised. Setting maxstd_boundrange to a
            # very large value keeps the inferred maxstd well above the
            # actual sigma range so the limiter never engages.
            "maxstd_boundrange": 1e20,
        }
        if self._seed is not None:
            # Offset the seed per restart so successive strategies do not
            # replay identical pseudo-random batches.
            options["seed"] = int(self._seed) + self._restarts_used
        return self._cma_module.CMAEvolutionStrategy(list(x0_t), self._sigma0, options)

    def _try_restart(self) -> bool:
        if self._restarts_used >= self._restarts:
            return False
        if self._n_eval >= self._max_evaluations:
            return False
        self._restarts_used += 1
        offset = self._restart_rng.uniform(-0.1, 0.1, size=self._x0_t.shape)
        x0_perturbed = np.clip(self._x0_t + offset, self._lower_t, self._upper_t)
        self._es = self._make_strategy(x0_perturbed)
        return True

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
        if self._n_eval >= self._max_evaluations:
            self._done = True
            return
        if self._es.stop():
            if not self._try_restart():
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
                break
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
            cost = (
                float(value)
                if (r.status == "completed" and math.isfinite(value))
                else FAILED_EVAL_COST
            )
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
            if self._n_eval >= self._max_evaluations:
                self._done = True
            elif self._es.stop():
                if not self._try_restart():
                    self._done = True

    def best(self) -> EvaluationResult | None:
        valid = [r for r in self._history if r.status == "completed"]
        if not valid:
            return None
        return min(valid, key=lambda r: r.objective_value)

    def converged(self) -> bool:
        return self._done


__all__ = ["CmaEsAdapter"]
