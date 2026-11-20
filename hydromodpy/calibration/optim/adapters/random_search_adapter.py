"""Random-search adapter using ``numpy.random.default_rng``."""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration.optim.method_config import RandomSearchMethodConfig
from hydromodpy.calibration.optim.optimizer import (
    EngineTraits,
    EvaluationResult,
    ParamSuggestion,
    best_completed,
)
from hydromodpy.calibration.optim.parameters import ParameterSpace
from hydromodpy.calibration.optim.sampling import physical_sample


class RandomSearchAdapter:
    """Random sampling using each parameter's sampling declaration."""

    traits = EngineTraits(libraries=("numpy",), fixed_plan=True)

    name = "random_search"
    options = RandomSearchMethodConfig

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
            values = {p.name: physical_sample(p, self._rng) for p in self.space}
            out.append(ParamSuggestion(trial_id=self._trial_id, values=values, source="ask"))
        return out

    def suggest_next(self) -> ParamSuggestion:
        return self.ask(1)[0]

    def tell(self, results: list[EvaluationResult]) -> None:
        self._history.extend(results)

    def best(self) -> EvaluationResult | None:
        return best_completed(self._history)

    def converged(self) -> bool:
        return False


__all__ = ["RandomSearchAdapter"]
