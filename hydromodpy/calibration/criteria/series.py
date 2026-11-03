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
from hydromodpy.core.metrics import (
    clip_negatives,
    kge,
    log_nse,
    mae,
    nse,
    nse_delta,
    nse_seasonal,
    rmse,
)
from hydromodpy.results.catalog.constants import METRIC_SENSE, cost_of

# Kernels that take a logarithm: negative values are clipped to zero and counted.
LOG_METRICS: frozenset[str] = frozenset({"nse_log"})

# Kernels whose cost is already a pure number: an efficiency score has no unit
# to remove, so dividing it by the spread of its own observations reweights the
# block rather than making it comparable to another.
DIMENSIONLESS: frozenset[str] = frozenset(
    {"nse", "kge", "nse_delta", "nse_seasonal", "nse_log", "reservoir"}
)

# The unit of the cost of a residual kernel: whatever the observations are in.
_OBSERVED_UNIT = "observed unit"


def _kge_score(sim: np.ndarray, obs: np.ndarray) -> float:
    """Scalar KGE score (2009 form); calibration needs a single number, not the decomposition."""
    return float(kge(sim, obs)["kge"])


# Window, in days, over which the reservoir objective differences the level.
# A day-to-day increment is wrecked by a two or three day phase shift even when the
# filling and emptying are right; ten days keeps the flux signal while making such a
# shift a perturbation rather than a sign flip. A coarser series differences one
# sample to the next.
RESERVOIR_INCREMENT_DAYS: float = 10.0

DAYS_PER_YEAR: float = 365.25
"""Length of the seasonal cycle, in days."""

# Kernels that read the dates of the series: the seasonal cycle and the
# increment window are lengths of time, so a monthly series holds them in fewer
# samples than a daily one, and a gap in the record is not one step.
SAMPLED_BY_DATE: frozenset[str] = frozenset({"nse_delta", "nse_seasonal", "reservoir"})


def _cycle_samples(sample_days: float | None) -> float:
    """Samples in one seasonal cycle. Without dates, the series is taken as daily."""
    if sample_days is None:
        return 365.0
    return DAYS_PER_YEAR / float(sample_days)


def _increment_samples(sample_days: float | None) -> int:
    """Samples in the increment window of the reservoir score."""
    if sample_days is None:
        return int(RESERVOIR_INCREMENT_DAYS)
    return max(1, round(RESERVOIR_INCREMENT_DAYS / float(sample_days)))


def _positions(times_days: Any, sample_days: float | None) -> np.ndarray | None:
    """Return the date of each sample counted in steps of the series, or ``None``.

    ``times_days`` is the date of each sample in days, from any origin.
    ``sample_days`` is the step; unset, the median spacing of the dates.
    """
    if times_days is None:
        return None
    days = np.asarray(times_days, dtype=float).ravel()
    if sample_days is None:
        spacing = np.diff(days)
        spacing = spacing[spacing > 0.0]
        if spacing.size == 0:
            return None
        sample_days = float(np.median(spacing))
    return (days - np.nanmin(days)) / float(sample_days) if days.size else days


def _seasonal_score(
    sim: np.ndarray,
    obs: np.ndarray,
    *,
    sample_days: float | None = None,
    times_days: Any = None,
) -> float:
    """``nse_seasonal`` with a cycle of one year of the series' own samples."""
    return nse_seasonal(
        sim, obs, period=_cycle_samples(sample_days), times=_positions(times_days, sample_days)
    )


def _delta_score(
    sim: np.ndarray,
    obs: np.ndarray,
    *,
    sample_days: float | None = None,
    times_days: Any = None,
) -> float:
    """``nse_delta`` from one sample to the next, never across a gap of the dates."""
    return nse_delta(sim, obs, times=_positions(times_days, sample_days))


# KGE is NOT offered on increments, on purpose. Its beta term is a ratio of means,
# and the mean of an increment series is (last - first) / n, i.e. near zero by
# construction, so the score swings wildly for one and the same run depending only
# on where the series is cut. NSE has no such term and stays stable, so the
# increment side of the objective uses it.


def _reservoir_score(
    sim: np.ndarray,
    obs: np.ndarray,
    *,
    sample_days: float | None = None,
    times_days: Any = None,
) -> float:
    """Half seasonal efficiency on the level, half efficiency on its increments.

    Built for an impounded level, where the two usual metrics mislead in opposite
    ways. ``nse`` on the level compares the model to a flat mean, a benchmark a
    strongly seasonal signal beats on its own, so a run can score comfortably and
    still be worse than the seasonal cycle. And a level is an integral, so
    compensating flux errors cancel in it: a low-water bias and a high-water bias of
    opposite signs hide behind a mean bias near zero while the increments stay
    uncorrelated.

    Pairing the two closes both holes: the seasonal term keeps the absolute level
    honest and demands more than climatology, the increment term makes the water
    balance count. Equal weights, no tuning knob, so the score stays readable.

    The increments are taken over ``RESERVOIR_INCREMENT_DAYS`` rather than one
    sample, so a timing error of a few days is not punished as though the model had
    filled when it should have emptied. ``sample_days`` is the sampling step of the
    series: the cycle and the window are counted in its samples. Without it the
    series is taken as daily. ``times_days``, the date of each sample in days,
    keeps the cycle in phase and the increments off a gap of the record.
    """
    seasonal = _seasonal_score(sim, obs, sample_days=sample_days, times_days=times_days)
    increments = nse_delta(
        sim,
        obs,
        step=_increment_samples(sample_days),
        times=_positions(times_days, sample_days),
    )
    if not np.isfinite(seasonal) or not np.isfinite(increments):
        return float("nan")
    return 0.5 * float(seasonal) + 0.5 * float(increments)


METRICS: dict[str, Callable[..., float]] = {
    "nse": nse,
    "rmse": rmse,
    "mae": mae,
    "kge": _kge_score,
    "nse_delta": _delta_score,
    "nse_seasonal": _seasonal_score,
    "nse_log": log_nse,
    "distance_gap": distance_gap,
    "distance_mean": distance_mean,
    "reservoir": _reservoir_score,
}

# Kernels whose score rises with agreement, so the cost is one minus the score.
# Read from the one table of metric directions; every other kernel is a cost.
HIGHER_IS_BETTER: frozenset[str] = frozenset(
    name for name in METRICS if METRIC_SENSE.get(name) == "max"
)


def clip_negatives_for_log_metric(
    simulated: np.ndarray,
    observed: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Clip negatives to zero for a log metric and count what was clipped.

    The rule is :func:`hydromodpy.core.metrics.clip_negatives`, the one the
    score of a run follows too. Returning the count is what stops the clipping
    from passing unnoticed, which would hide a sign error in a reconstruction.
    """
    return clip_negatives(simulated, observed)


class SeriesCriterion:
    """One scoring kernel of the registry, with its conventions declared."""

    def __init__(self, name: str, kernel: Any) -> None:
        self.name = str(name)
        self._kernel = kernel
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
            sim, obs, n_clipped = clip_negatives_for_log_metric(sim, obs)
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
    "DIMENSIONLESS",
    "HIGHER_IS_BETTER",
    "LOG_METRICS",
    "METRICS",
    "DAYS_PER_YEAR",
    "RESERVOIR_INCREMENT_DAYS",
    "SAMPLED_BY_DATE",
    "SeriesCriterion",
    "clip_negatives_for_log_metric",
]
