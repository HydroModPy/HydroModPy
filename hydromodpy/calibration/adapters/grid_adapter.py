"""Grid-search adapter — deterministic, no external dependency."""

from __future__ import annotations

import itertools
from typing import Iterator

import numpy as np

from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    register_optimizer,
)
from hydromodpy.calibration.parameters import ParameterSpace


@register_optimizer("grid")
class GridAdapter:
    """Regular grid over transformed bounds."""

    name = "grid"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        points_per_dim: int | list[int] = 5,
        seed: int | None = None,
    ):
        self.space = space
        if isinstance(points_per_dim, int):
            per_dim = [points_per_dim] * space.dim
        else:
            if len(points_per_dim) != space.dim:
                raise ValueError("points_per_dim length must match space dim")
            per_dim = list(points_per_dim)
        axes: list[np.ndarray] = []
        for p, n in zip(space.parameters, per_dim):
            low, high = p.lower_transformed, p.upper_transformed
            axes.append(np.linspace(low, high, n))
        self._grid: Iterator[tuple[float, ...]] = iter(itertools.product(*axes))
        self._history: list[EvaluationResult] = []
        self._trial_id = 0
        self._exhausted = False

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            try:
                point = next(self._grid)
            except StopIteration:
                self._exhausted = True
                break
            self._trial_id += 1
            values = {
                p.name: p.to_physical(float(point[i]))
                for i, p in enumerate(self.space.parameters)
            }
            out.append(
                ParamSuggestion(trial_id=self._trial_id, values=values, source="ask")
            )
        return out

    def suggest_next(self) -> ParamSuggestion:
        got = self.ask(1)
        if not got:
            raise StopIteration("grid exhausted")
        return got[0]

    def tell(self, results: list[EvaluationResult]) -> None:
        self._history.extend(results)

    def best(self) -> EvaluationResult | None:
        valid = [r for r in self._history if r.status == "completed"]
        if not valid:
            return None
        return min(valid, key=lambda r: r.objective_value)

    def converged(self) -> bool:
        return self._exhausted


__all__ = ["GridAdapter"]
