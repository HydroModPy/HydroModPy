"""Every metric of the registry, as a criterion.

The ten scoring kernels stay exactly what they were: this wraps each one and
takes over the two conventions that used to live in the objective and had to be
re-applied by every caller. The sign, because half the kernels return a score
where higher is better and a cost must be minimized. And the clipping, because a
log metric cannot take a negative value while a discharge reconstructed below a
dam legitimately holds a few.

Both were correct where they were. Neither was declared, so nothing could be
asked about a metric before running it: whether its cost carries a unit, whether
a burn-in in samples applies, whether a root search may be pointed at it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

from hydromodpy.calibration.criteria.base import (
    SERIES_SUPPORTS,
    CriterionRequirements,
    CriterionResult,
)
from hydromodpy.calibration.criteria.hydrographic_network_distance import (
    distance_gap,
    distance_mean,
)
from hydromodpy.core.scoring.metric_table import METRIC_SPECS, TRIAL_METRIC_NAMES
from hydromodpy.core.scoring.metrics import (
    DATED_KERNELS,
    clip_negatives,
    kge,
    log_nse,
    mae,
    nse,
    rmse,
)
from hydromodpy.results.catalog.constants import cost_of

# The unit of the cost of a residual kernel: whatever the observations are in.
_OBSERVED_UNIT = "observed unit"


def _kge_score(sim: np.ndarray, obs: np.ndarray) -> float:
    """Scalar KGE score (2009 form); calibration needs a single number, not the decomposition."""
    return float(kge(sim, obs)["kge"])


# The kernels that read the dates live in core/scoring, where a stored run reads them too.
# KGE is NOT offered on increments, on purpose. Its beta term is a ratio of means,
# and the mean of an increment series is (last - first) / n, i.e. near zero by
# construction, so the score swings wildly for one and the same run depending only
# on where the series is cut. NSE has no such term and stays stable, so the
# increment side of the objective uses it.

SAMPLED_BY_DATE: frozenset[str] = frozenset(
    name for name in DATED_KERNELS if name in TRIAL_METRIC_NAMES
)
"""Trial kernels that read the dates of the series: a year and a window are counted in
its samples, and a gap in the record is not one step."""


METRICS: dict[str, Callable[..., float]] = {
    "nse": nse,
    "rmse": rmse,
    "mae": mae,
    "kge": _kge_score,
    "nse_delta": DATED_KERNELS["nse_delta"],
    "nse_seasonal": DATED_KERNELS["nse_seasonal"],
    "nse_log": log_nse,
    "distance_gap": distance_gap,
    "distance_mean": distance_mean,
    "reservoir": DATED_KERNELS["reservoir"],
    "bfi_error": DATED_KERNELS["bfi_error"],
}

# Kernels whose score rises with agreement, so the cost is one minus the score.
# Read from the one table of metric directions; every other kernel is a cost.
HIGHER_IS_BETTER: frozenset[str] = frozenset(
    name for name in METRICS if METRIC_SPECS[name].sense == "max"
)


class SeriesCriterion:
    """One scoring kernel of the registry, with its conventions declared."""

    def __init__(self, name: str, kernel: Any) -> None:
        self.name = str(name)
        self._kernel = kernel
        self._takes_log = METRIC_SPECS[self.name].clips_negatives

    def requirements(self) -> CriterionRequirements:
        """A series criterion fits observations and publishes no residual.

        It reads a series, so it scores the supports that produce one and no
        other: a network output hands it two distances, not a chronicle.
        """
        # An efficiency score has no unit to remove, so dividing it by the spread of its
        # own observations reweights the block rather than making it comparable.
        dimensionless = METRIC_SPECS[self.name].dimensionless
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
        *,
        sample_days: float | None = None,
        times_days: Sequence[float] | Any | None = None,
    ) -> CriterionResult:
        """Return the cost, minimized, with what the clipping had to touch.

        ``sample_days`` is the sampling step of the series, in days. The kernels
        of :data:`SAMPLED_BY_DATE` count their cycle and window in it; the
        others ignore it. Unset, those kernels take the series as daily.
        ``times_days`` is the date of each sample in days: those kernels read
        a gap of the record from it. Unset, the samples are taken as regular.
        """
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
            sim, obs, n_clipped = clip_negatives(sim, obs)
        if self.name in SAMPLED_BY_DATE and (sample_days is not None or times_days is not None):
            raw = float(self._kernel(sim, obs, sample_days=sample_days, times_days=times_days))
        else:
            raw = float(self._kernel(sim, obs))
        cost = cost_of(self.name, raw)
        diagnostics = {"score": raw, "n_values": float(obs.size)}
        if self._takes_log:
            diagnostics["n_clipped"] = float(n_clipped)
        return CriterionResult(cost=float(cost), diagnostics=diagnostics)


__all__ = [
    "HIGHER_IS_BETTER",
    "METRICS",
    "SAMPLED_BY_DATE",
    "SeriesCriterion",
]
