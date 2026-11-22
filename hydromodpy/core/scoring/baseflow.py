"""The baseflow index of a daily discharge, by the Wallingford filter, for one or two series.

The Wallingford method (Gustard et al. 1992, the Institute of Hydrology) takes the
minimum of each block of five days, keeps the minima that stand below 1/0.9 of their
neighbours as turning points, and draws the baseflow as the straight line between
them, never above the discharge. The baseflow index (BFI) is the share of the
discharge that this line holds: near 1 for a stream fed by its aquifer, lower for one
fed by quick runoff. It reads daily values only: a block of five months says nothing
about a recession.

To compare a simulated and an observed discharge, both are filtered on the same days,
the record is cut at its gaps, and each index sums only the days where both baselines
exist, so a turning point that one series has and the other lacks shifts neither.
"""

from __future__ import annotations

import numpy as np

DAILY_STEP_DAYS = (0.5, 1.5)
"""The median spacing, in days, a series must have to be read as daily."""

MIN_PIECE_DAYS = 15
"""The shortest stretch without a gap that the filter reads: three blocks of five days."""


def wallingford(discharge: np.ndarray) -> np.ndarray:
    """Baseflow by the smoothed minima of blocks of 5 days (Gustard et al. 1992).

    The minimum of a block is a turning point when 0.9 times it stays below the
    minima of the blocks on each side. The baseflow is the straight line between
    turning points, never above the discharge, and NaN outside the first and the
    last turning point (ESPERE writes 0 there, which lowers those years).
    """
    q = np.asarray(discharge, dtype=np.float64)
    n_blocks = q.size // 5
    if n_blocks < 3:
        return np.full(q.size, np.nan)
    blocks = q[: n_blocks * 5].reshape(n_blocks, 5)
    minima = blocks.min(axis=1)
    where = np.arange(n_blocks) * 5 + blocks.argmin(axis=1)
    turning = [
        b
        for b in range(1, n_blocks - 1)
        if 0.9 * minima[b] <= minima[b - 1] and 0.9 * minima[b] <= minima[b + 1]
    ]
    baseflow = np.full(q.size, np.nan)
    if len(turning) < 2:
        return baseflow
    days = where[turning]
    span = np.arange(days[0], days[-1] + 1)
    baseflow[span] = np.minimum(q[span], np.interp(span, days, minima[turning]))
    return baseflow


def _pieces(times_days: np.ndarray) -> list[slice]:
    """Stretches of consecutive days, cut where a day is missing."""
    cuts = np.flatnonzero(np.diff(times_days) > 1.5) + 1
    bounds = np.concatenate([[0], cuts, [times_days.size]])
    return [
        slice(a, b) for a, b in zip(bounds[:-1], bounds[1:], strict=True) if b - a >= MIN_PIECE_DAYS
    ]


def baseflow_indices(
    simulated: np.ndarray, observed: np.ndarray, *, times_days: np.ndarray | None = None
) -> tuple[float, float]:
    """The BFI of ``simulated`` and of ``observed``, on the same days, NaN unless daily.

    ``times_days`` is the date of each sample in days; unset, the samples are taken
    as consecutive days. A pair with a NaN on either side is dropped first.
    """
    sim = np.asarray(simulated, dtype=np.float64).ravel()
    obs = np.asarray(observed, dtype=np.float64).ravel()
    days = (
        np.arange(sim.size, dtype=np.float64)
        if times_days is None
        else np.asarray(times_days, dtype=np.float64).ravel()
    )
    keep = np.isfinite(sim) & np.isfinite(obs) & np.isfinite(days)
    sim, obs, days = sim[keep], obs[keep], days[keep]
    if sim.size < MIN_PIECE_DAYS:
        return float("nan"), float("nan")
    step = float(np.median(np.diff(days)))
    if not DAILY_STEP_DAYS[0] <= step <= DAILY_STEP_DAYS[1]:
        return float("nan"), float("nan")
    sums = np.zeros(4)
    for piece in _pieces(days):
        base_sim, base_obs = wallingford(sim[piece]), wallingford(obs[piece])
        both = np.isfinite(base_sim) & np.isfinite(base_obs)
        sums += (
            base_sim[both].sum(),
            sim[piece][both].sum(),
            base_obs[both].sum(),
            obs[piece][both].sum(),
        )
    if sums[1] <= 0.0 or sums[3] <= 0.0:
        return float("nan"), float("nan")
    return float(sums[0] / sums[1]), float(sums[2] / sums[3])


__all__ = ["DAILY_STEP_DAYS", "MIN_PIECE_DAYS", "baseflow_indices", "wallingford"]
