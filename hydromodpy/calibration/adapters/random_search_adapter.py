"""Random-search adapter using ``numpy.random.default_rng`` for parity.

Matches the legacy ``_driver_random_search`` byte-for-byte: same seed seeds a
``default_rng``; ``rng.random(dim)`` draws a unit-cube vector mapped to
transformed bounds. Optuna ``RandomSampler`` would draw a different sequence,
breaking goldens calibrated on the legacy RNG.
"""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    register_optimizer,
)
from hydromodpy.calibration.parameters import ParameterSpace


@register_optimizer("random_search")
class RandomSearchAdapter:
    """Uniform random sampling in transformed parameter space."""

    name = "random_search"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        seed: int | None = None,
        n_samples: int | None = None,
        **_unused,
    ) -> None:
        del n_samples
        self.space = space
        self._rng = np.random.default_rng(None if seed is None else int(seed))
        self._lower = np.array([p.lower_transformed for p in space.parameters], dtype=float)
        self._upper = np.array([p.upper_transformed for p in space.parameters], dtype=float)
        self._span = self._upper - self._lower
        self._history: list[EvaluationResult] = []
        self._trial_id = 0

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            unit = self._rng.random(self._lower.size)
            transformed = self._lower + unit * self._span
            self._trial_id += 1
            values = {
                p.name: p.to_physical(float(transformed[i]))
                for i, p in enumerate(self.space.parameters)
            }
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
