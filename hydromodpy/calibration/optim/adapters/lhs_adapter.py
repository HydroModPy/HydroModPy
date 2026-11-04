"""Stratified Latin hypercube adapter, built on ``scipy.stats.qmc``.

The design is drawn once, in the unit hypercube, with
:class:`scipy.stats.qmc.LatinHypercube`: with ``optimization=None`` or
``"random-cd"``, every dimension is cut into ``n_samples`` strata and each
stratum is hit exactly once, which a column of independent uniform draws
does not guarantee. ``optimization="lloyd"`` is scipy's Lloyd-relaxation
post-process: it spreads points apart for better spacing but, by scipy's own
documentation, does not guarantee that this one-point-per-stratum property
survives, so it can leave strata unsampled or hit more than once. Each unit
column is then mapped into the search space of its parameter.

A uniform sampling is affine in search space: ``lower_transformed +
u * (upper_transformed - lower_transformed)``. A log-uniform sampling is mapped
through ``scipy.stats.loguniform.ppf``, its quantile function, in physical
space, then converted to search space with ``to_physical`` undone by
``to_transformed`` - the same function :mod:`sampling` applies to one
Monte Carlo draw, applied here to a stratified column so the stratification
survives the log mapping. A normal sampling has no stratification scheme this
adapter implements, so it is refused by name rather than silently treated as
uniform.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
from scipy.stats import loguniform, qmc

from hydromodpy.calibration.optim.optimizer import (
    EngineTraits,
    EvaluationResult,
    ParamSuggestion,
    best_completed,
    register_optimizer,
)
from hydromodpy.calibration.optim.parameters import (
    CalibParameter,
    ParameterSpace,
    refuse_normal_sampling,
)
from hydromodpy.calibration.optim.stopping import CountedBudget


def _stratified_column(param: CalibParameter, unit_column: np.ndarray) -> np.ndarray:
    """Map one stratified unit-interval column into *param*'s search space."""
    refuse_normal_sampling("lhs", param.name, param.sampling)
    if param.sampling == "log_uniform":
        physical = loguniform.ppf(unit_column, float(param.lower), float(param.upper))
        return np.asarray([param.to_transformed(float(v)) for v in physical], dtype=float)
    low, high = param.lower_transformed, param.upper_transformed
    return low + unit_column * (high - low)


def design_budget(n_samples: int) -> CountedBudget:
    """Count the points of the design, before the first solve."""
    return CountedBudget(counts=(int(n_samples),), step="design point")


@register_optimizer("lhs")
class LhsAdapter:
    """Stratified Latin hypercube design over transformed bounds."""

    # The design is exhausted after one draw: repeating it with a different
    # seed gives a different design, but the same seed is the same computation
    # twice.
    traits = EngineTraits(draws_a_normal=False, restarts_explore_differently=True)

    name = "lhs"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        n_samples: int,
        optimization: Literal["random-cd", "lloyd"] | None = None,
        seed: int | None = None,
    ) -> None:
        if n_samples <= 0:
            raise ValueError(f"n_samples must be positive, got {n_samples!r}")
        self.space = space
        self.n_samples = int(n_samples)
        sampler = qmc.LatinHypercube(
            d=space.dim, optimization=optimization, seed=None if seed is None else int(seed)
        )
        unit_design = sampler.random(n=self.n_samples)
        columns = [
            _stratified_column(param, unit_design[:, i]) for i, param in enumerate(space.parameters)
        ]
        self._design = np.column_stack(columns) if columns else np.empty((self.n_samples, 0))
        self._cursor = 0
        self._history: list[EvaluationResult] = []
        self._trial_id = 0

    @property
    def counted_budget(self) -> CountedBudget:
        """The whole design, counted up front: ``"auto"`` budgets exactly it."""
        return design_budget(self.n_samples)

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        end = min(self._cursor + n, self.n_samples)
        for row in self._design[self._cursor : end]:
            self._trial_id += 1
            values = {
                p.name: p.to_physical(float(row[i])) for i, p in enumerate(self.space.parameters)
            }
            out.append(ParamSuggestion(trial_id=self._trial_id, values=values, source="ask"))
        self._cursor = end
        return out

    def suggest_next(self) -> ParamSuggestion:
        got = self.ask(1)
        if not got:
            raise StopIteration("lhs design exhausted")
        return got[0]

    def tell(self, results: list[EvaluationResult]) -> None:
        self._history.extend(results)

    def best(self) -> EvaluationResult | None:
        return best_completed(self._history)

    def converged(self) -> bool:
        return self._cursor >= self.n_samples


__all__ = ["LhsAdapter", "design_budget"]
