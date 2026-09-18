"""Every metric of the registry, as a criterion.

The ten scoring kernels stay exactly what they were: this wraps each one and
takes over the two conventions that used to live in the objective and had to be
re-applied by every caller. The sign, because half the kernels return a score
where higher is better and a cost must be minimised. And the clipping, because a
log metric refuses a negative value while a discharge reconstructed below a dam
legitimately holds a few.

Both were correct where they were. Neither was declared, so nothing could be
asked about a metric before running it: whether its cost carries a unit, whether
a burn-in in samples applies, whether a root search may be pointed at it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from hydromodpy.calibration.criteria.base import (
    SERIES_SUPPORTS,
    CriterionRequirements,
    CriterionResult,
)

# Kernels whose score rises with agreement, so the cost is one minus the score.
HIGHER_IS_BETTER: frozenset[str] = frozenset(
    {"nse", "kge", "nse_delta", "nse_seasonal", "nse_log", "reservoir"}
)

# Kernels that take a logarithm and therefore refuse a negative value.
LOG_METRICS: frozenset[str] = frozenset({"nse_log"})

# Kernels whose cost is already a pure number: an efficiency score has no unit
# to remove, so dividing it by the spread of its own observations reweights the
# block rather than making it comparable to another.
DIMENSIONLESS: frozenset[str] = frozenset(
    {"nse", "kge", "nse_delta", "nse_seasonal", "nse_log", "reservoir"}
)

# The unit of the cost of a residual kernel: whatever the observations are in.
_OBSERVED_UNIT = "observed unit"


def clip_negatives_for_log_metric(
    simulated: np.ndarray,
    observed: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Clip negatives to zero for a log metric and count what was clipped.

    Returning the count is what stops the clipping from passing unnoticed, which
    would hide a sign error in a reconstruction.
    """
    sim = np.asarray(simulated, dtype=float)
    obs = np.asarray(observed, dtype=float)
    n_clipped = int(np.count_nonzero(sim < 0.0) + np.count_nonzero(obs < 0.0))
    if n_clipped == 0:
        return sim, obs, 0
    return np.clip(sim, 0.0, None), np.clip(obs, 0.0, None), n_clipped


class SeriesCriterion:
    """One scoring kernel of the registry, with its conventions declared."""

    def __init__(self, name: str, kernel: Any) -> None:
        self.name = str(name)
        self._kernel = kernel
        self._higher_is_better = self.name in HIGHER_IS_BETTER
        self._takes_log = self.name in LOG_METRICS

    def requirements(self) -> CriterionRequirements:
        """A series criterion fits observations and publishes no residual.

        It reads a series, so it scores the supports that produce one and no
        other: a network output hands it two distances, not a chronicle.
        """
        dimensionless = self.name in DIMENSIONLESS
        return CriterionRequirements(
            needs_observations=True,
            has_time_axis=True,
            signed=False,
            cost_is_dimensionless=dimensionless,
            reads_supports=SERIES_SUPPORTS,
            cost_unit=None if dimensionless else _OBSERVED_UNIT,
        )

    def score(
        self,
        simulated: Sequence[float] | Any,
        observed: Sequence[float] | Any | None = None,
    ) -> CriterionResult:
        """Return the cost, minimised, with what the clipping had to touch."""
        if observed is None:
            raise ValueError(f"criterion {self.name!r} fits observations and none were supplied")
        sim = np.asarray(simulated, dtype=float).ravel()
        obs = np.asarray(observed, dtype=float).ravel()
        if sim.size != obs.size:
            raise ValueError(
                f"criterion {self.name!r}: simulated length {sim.size} does not match "
                f"observed length {obs.size}"
            )
        n_clipped = 0
        if self._takes_log:
            sim, obs, n_clipped = clip_negatives_for_log_metric(sim, obs)
        raw = float(self._kernel(sim, obs))
        cost = (1.0 - raw) if self._higher_is_better else raw
        diagnostics = {"score": raw, "n_values": float(obs.size)}
        if self._takes_log:
            diagnostics["n_clipped"] = float(n_clipped)
        return CriterionResult(cost=float(cost), diagnostics=diagnostics)


__all__ = [
    "DIMENSIONLESS",
    "HIGHER_IS_BETTER",
    "LOG_METRICS",
    "SeriesCriterion",
    "clip_negatives_for_log_metric",
]
