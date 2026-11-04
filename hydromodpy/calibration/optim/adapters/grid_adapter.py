"""Grid-search adapter - deterministic, no external dependency."""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterator

import numpy as np

from hydromodpy.calibration.optim.optimizer import (
    EngineTraits,
    EvaluationResult,
    ParamSuggestion,
    best_completed,
    register_optimizer,
)
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.optim.stopping import CountedBudget

DEFAULT_POINTS_PER_DIM = 5
"""Points per parameter when ``points_per_dim`` is left unwritten."""


def grid_axes_sizes(n_parameters: int, points_per_dim: int | list[int] | None) -> list[int]:
    """Return how many points the grid places along each parameter."""
    if points_per_dim is None:
        points_per_dim = DEFAULT_POINTS_PER_DIM
    if isinstance(points_per_dim, int):
        return [points_per_dim] * n_parameters
    if len(points_per_dim) != n_parameters:
        raise ValueError("points_per_dim length must match space dim")
    return list(points_per_dim)


def grid_budget(n_parameters: int, points_per_dim: int | list[int] | None) -> CountedBudget:
    """Count the points of the grid, before the first solve."""
    return CountedBudget(
        counts=(math.prod(grid_axes_sizes(n_parameters, points_per_dim)),), step="grid point"
    )


@register_optimizer("grid")
class GridAdapter:
    """Regular grid over transformed bounds."""

    # An exhaustive sweep visits the same points in the same order whatever the
    # seed, so repeating it is the same computation twice.
    traits = EngineTraits(restarts_explore_differently=False, fixed_plan=True)

    name = "grid"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        points_per_dim: int | list[int] | None = None,
        seed: int | None = None,
    ):
        self.space = space
        self._points_per_dim = points_per_dim
        per_dim = grid_axes_sizes(space.dim, points_per_dim)
        axes: list[np.ndarray] = []
        for p, n in zip(space.parameters, per_dim, strict=False):
            low, high = p.lower_transformed, p.upper_transformed
            axes.append(np.linspace(low, high, n))
        self._n_points = math.prod(len(axis) for axis in axes)
        self._grid: Iterator[tuple[float, ...]] = iter(itertools.product(*axes))
        self._history: list[EvaluationResult] = []
        self._trial_id = 0

    @property
    def counted_budget(self) -> CountedBudget:
        """The whole grid, counted up front: ``"auto"`` budgets every point of it."""
        return grid_budget(self.space.dim, self._points_per_dim)

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            try:
                point = next(self._grid)
            except StopIteration:
                break
            self._trial_id += 1
            values = {
                p.name: p.to_physical(float(point[i])) for i, p in enumerate(self.space.parameters)
            }
            out.append(ParamSuggestion(trial_id=self._trial_id, values=values, source="ask"))
        return out

    def suggest_next(self) -> ParamSuggestion:
        got = self.ask(1)
        if not got:
            raise StopIteration("grid exhausted")
        return got[0]

    def tell(self, results: list[EvaluationResult]) -> None:
        self._history.extend(results)

    def best(self) -> EvaluationResult | None:
        return best_completed(self._history)

    def converged(self) -> bool:
        """Whether every point of the grid was handed out."""
        return self._trial_id >= self._n_points


__all__ = ["DEFAULT_POINTS_PER_DIM", "GridAdapter", "grid_axes_sizes", "grid_budget"]
