"""Random-search adapter using ``numpy.random.default_rng``."""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration.adapters._prior_sampling import physical_prior_sample
from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    register_optimizer,
)
from hydromodpy.calibration.parameters import ParameterSpace


@register_optimizer("random_search")
class RandomSearchAdapter:
    """Random sampling using each parameter prior declaration."""

    name = "random_search"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        seed: int | None = None,
    ) -> None:
        self.space = space
        self._rng = np.random.default_rng(None if seed is None else int(seed))
        self._history: list[EvaluationResult] = []
        self._trial_id = 0

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            self._trial_id += 1
            values = {p.name: physical_prior_sample(p, self._rng) for p in self.space}
            out.append(ParamSuggestion(trial_id=self._trial_id, values=values, source="ask"))
        return out

    def suggest_next(self) -> ParamSuggestion:
        return self.ask(1)[0]

    def tell(self, results: list[EvaluationResult]) -> None:
        self._history.extend(results)

    def best(self) -> EvaluationResult | None:
        valid = [r for r in self._history if r.status == "completed"]
        if not valid:
            return None
        return min(valid, key=lambda r: r.objective_value)

    def converged(self) -> bool:
        return False


__all__ = ["RandomSearchAdapter"]
