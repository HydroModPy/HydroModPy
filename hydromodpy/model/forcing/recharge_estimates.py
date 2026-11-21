"""Recharge estimated from the weather, the gauge or the piezometers, to compare with the run.

None of these numbers enters the model. They give a range of recharge for the
same catchment, the way ESPERE does (BRGM RP-69538-FR, Lanini et al. 2016), and
the run's own recharge is set beside them. Every function takes plain arrays and
returns mm, so a reader can check one formula without the rest.

Three families:

- From the weather, one value a year. ``turc`` gives an effective rainfall,
  ``guttman_zuckerman`` and ``kessler`` give a recharge. They were fitted on
  given climates (Kessler on a Hungarian karst, Guttman and Zuckerman on a
  Mediterranean one), so they bound the answer more than they give it.
- From the gauge, a daily baseflow taken as the recharge that leaves the
  aquifer: ``wallingford`` (Gustard et al. 1992), ``chapman_maxwell`` (1996) and
  ``eckhardt`` (2005). ``closing_factor`` is the number that would scale the
  run's recharge and runoff onto the gauged volume, equation 12 of Abherve (2022).
- From a piezometer, ``wtf``: the rises of the water table times the specific
  yield (Healy and Cook 2002), with the decline the rain interrupted added back
  when ``correction = "recession"`` (after the EMR method of Nimmo et al. 2015).

Where ESPERE's code departs from its method, this module keeps the method: the
threshold of 1000 mm of Guttman and Zuckerman belongs to the third branch, the
steps of Kessler leave no gap between 0.70 and 0.71, and the recession of WTF is
fitted on the daily declines, not on the logarithm of the raw elevation, so the
answer does not depend on the datum.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

GAP_DAYS_DISCHARGE = 3
GAP_DAYS_HEAD = 5
"""Longest gap filled by a straight line, as ESPERE does; a longer one cuts the series."""

SHARE_OF_A_YEAR = 0.9
"""A year counts when its series covers this share of its days."""


# ---------------------------------------------------------------------------
# Weather, one value a year
# ---------------------------------------------------------------------------


def turc(precipitation_mm: np.ndarray, temperature_c: np.ndarray) -> np.ndarray:
    """Annual effective rainfall, mm, from the annual rain and mean temperature (Turc 1954)."""
    capacity = 300.0 + 25.0 * temperature_c + 0.05 * temperature_c**3
    # Under about -10 degC of yearly mean the capacity L is no longer positive.
    safe = np.where(capacity > 0, capacity, np.nan)
    return precipitation_mm * (1.0 - 1.0 / np.sqrt(0.9 + (precipitation_mm / safe) ** 2))


def guttman_zuckerman(precipitation_mm: np.ndarray) -> np.ndarray:
    """Annual recharge, mm, by the three straight lines of Guttman and Zuckerman (1995).

    Below 180 mm of rain the first line falls under zero, and the recharge is 0.
    """
    p = np.asarray(precipitation_mm, dtype=np.float64)
    recharge = np.where(
        p < 600.0, 0.45 * (p - 180.0), np.where(p < 1000.0, 0.88 * (p - 410.0), 0.97 * (p - 463.0))
    )
    return np.maximum(recharge, 0.0)


KESSLER_STEPS = (
    (0.05, 0.0),
    (0.15, 1.0),
    (0.25, 2.0),
    (0.35, 3.0),
    (0.45, 4.0),
    (0.55, 5.0),
    (0.60, 7.0),
    (0.65, 10.0),
    (0.70, 13.0),
)
"""Upper bound of ``|CPR|`` and the correction it gives; 15 above the last bound."""


def kessler_correction(cpr: float) -> float:
    """The correction of the determinative rate, with the sign of ``cpr`` (Kessler 1967)."""
    for bound, step in KESSLER_STEPS:
        if abs(cpr) < bound:
            return float(np.sign(cpr)) * step
    return float(np.sign(cpr)) * 15.0


def kessler(
    precipitation_mm: np.ndarray, january_april_mm: np.ndarray, september_december_mm: np.ndarray
) -> np.ndarray:
    """Annual recharge, mm, from the share of rain that falls from January to April (Kessler 1967).

    The three arrays hold one value per consecutive year. The share is corrected
    by how wet the previous autumn was against the mean autumn, so the first
    year has no value (NaN).
    """
    autumn_mean = float(np.mean(september_december_mm))
    recharge = np.full(len(precipitation_mm), np.nan)
    for j in range(1, len(precipitation_mm)):
        cpr = (september_december_mm[j - 1] - autumn_mean) / autumn_mean
        mu = 100.0 * january_april_mm[j] / precipitation_mm[j] + kessler_correction(cpr)
        rate = 0.0003 * mu**3 - 0.0339 * mu**2 + 2.2778 * mu - 1.5758
        recharge[j] = rate * precipitation_mm[j] / 100.0
    return recharge


# ---------------------------------------------------------------------------
# Gauge, a daily baseflow
# ---------------------------------------------------------------------------


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


def _start_of(q: np.ndarray) -> float:
    return float(np.min(q[:5]))


def chapman_maxwell(discharge: np.ndarray, k: float) -> np.ndarray:
    """Baseflow by the one-parameter filter of Chapman and Maxwell (1996)."""
    q = np.asarray(discharge, dtype=np.float64)
    baseflow = np.empty_like(q)
    baseflow[0] = _start_of(q)
    for t in range(1, q.size):
        baseflow[t] = min(q[t], (k * baseflow[t - 1] + (1.0 - k) * q[t]) / (2.0 - k))
    return baseflow


def eckhardt(discharge: np.ndarray, k: float, bfi_max: float) -> np.ndarray:
    """Baseflow by the two-parameter filter of Eckhardt (2005)."""
    q = np.asarray(discharge, dtype=np.float64)
    baseflow = np.empty_like(q)
    baseflow[0] = _start_of(q)
    for t in range(1, q.size):
        baseflow[t] = min(
            q[t],
            ((1.0 - bfi_max) * k * baseflow[t - 1] + (1.0 - k) * bfi_max * q[t])
            / (1.0 - k * bfi_max),
        )
    return baseflow


def recession_constant(discharge: np.ndarray, *, min_days: int = 5, skip_days: int = 2) -> float:
    """Daily recession constant ``k`` of the gauge, between 0 and 1, or NaN.

    Every run of at least ``min_days`` falling days is a recession. Its first
    ``skip_days`` still carry quick flow and are dropped, then the mean slope of
    ``ln Q`` over the rest gives ``k = exp(slope)``. ESPERE builds a master
    recession curve (Posavec et al. 2006) for the same number; this simpler
    reading keeps one rule a reader can follow.
    """
    q = np.asarray(discharge, dtype=np.float64)
    falling = np.diff(q) < 0
    slopes: list[float] = []
    start = None
    for t, down in enumerate(np.append(falling, False)):
        if down and start is None:
            start = t
        elif not down and start is not None:
            if t - start >= min_days and np.all(q[start : t + 1] > 0):
                segment = np.log(q[start + skip_days : t + 1])
                if segment.size >= 2:
                    slopes.append(float(np.mean(np.diff(segment))))
            start = None
    if not slopes:
        return float("nan")
    return float(np.exp(np.mean(slopes)))


# ---------------------------------------------------------------------------
# Piezometer, the rises of the water table
# ---------------------------------------------------------------------------


def wtf(head_m: np.ndarray, specific_yield: float, *, correction: str = "recession") -> np.ndarray:
    """Daily recharge, mm, by water table fluctuation; the series must have no gap.

    ``none`` sums the daily rises (RISE). ``recession`` adds to each rise the
    decline the water table would have made without it: on each recession of 6
    days or more that falls by more than 2 cm, the daily decline is fitted as an
    exponential of time and extended to the start of the next recession. The
    missed decline is booked on the day that next recession starts. Fitting the
    declines, not the levels, keeps the answer free of the datum.
    """
    h = np.asarray(head_m, dtype=np.float64)
    rises = np.zeros_like(h)
    rises[1:] = np.maximum(np.diff(h), 0.0)
    if correction == "none":
        return 1000.0 * specific_yield * rises

    tolerance = 0.01
    added = np.zeros_like(h)
    recessions = _recessions(h, tolerance)
    for (start, end), (next_start, _) in zip(recessions[:-1], recessions[1:], strict=True):
        if end - start + 1 < 6 or h[start] - h[end] <= 2 * tolerance:
            continue
        declines = -np.diff(h[start : end + 1])
        days = np.arange(declines.size, dtype=np.float64)
        falling = declines > 0
        if falling.sum() < 3:
            continue
        slope, intercept = np.polyfit(days[falling], np.log(declines[falling]), 1)
        if slope >= 0:
            continue  # declines that do not fade are no recession to extend
        missed_days = np.arange(declines.size, next_start - start, dtype=np.float64)
        added[next_start] += float(np.sum(np.exp(intercept + slope * missed_days)))
    return 1000.0 * specific_yield * (rises + added)


def _recessions(h: np.ndarray, tolerance: float) -> list[tuple[int, int]]:
    """Index of the start (a peak) and the end of each recession of ``h``."""
    spans: list[tuple[int, int]] = []
    t = 1
    while t < h.size - 1:
        if h[t] >= h[t - 1] and h[t] > h[t + 1]:
            start = t
            t += 1
            while t < h.size and h[t] < h[t - 1] + tolerance:
                if t + 1 < h.size and h[t] >= h[t - 1] and h[t] < h[t + 1]:
                    break
                t += 1
            spans.append((start, t - 1))
        else:
            t += 1
    return spans


# ---------------------------------------------------------------------------
# Series handling
# ---------------------------------------------------------------------------


def daily_pieces(series: pd.Series, max_gap_days: int) -> list[pd.Series]:
    """Cut a daily series at gaps longer than ``max_gap_days``; fill the shorter ones linearly."""
    series = series.dropna().sort_index()
    if series.empty:
        return []
    series.index = pd.DatetimeIndex(series.index).normalize()
    series = series.groupby(level=0).mean()
    full = series.reindex(pd.date_range(series.index[0], series.index[-1], freq="D"))
    missing = full.isna().to_numpy()
    pieces, start, t = [], 0, 0
    while t < missing.size:
        if not missing[t]:
            t += 1
            continue
        gap_start = t
        while t < missing.size and missing[t]:
            t += 1
        if t - gap_start > max_gap_days:
            pieces.append(full.iloc[start:gap_start])
            start = t
    pieces.append(full.iloc[start:])
    return [piece.interpolate(limit_area="inside") for piece in pieces if piece.notna().sum() >= 10]


def annual_totals(daily: pd.Series) -> pd.Series:
    """Sum of a daily series per calendar year, for years covered on 90 % of their days.

    A year covered on fewer days is scaled to the full year from the days it has.
    """
    daily = daily.dropna()
    if daily.empty:
        return pd.Series(dtype=np.float64)
    years = daily.index.year
    counts = daily.groupby(years).size()
    length = pd.Series(
        [
            366 if pd.Timestamp(year=int(y), month=1, day=1).is_leap_year else 365
            for y in counts.index
        ],
        index=counts.index,
    )
    kept = counts.index[counts >= SHARE_OF_A_YEAR * length]
    means = daily.groupby(years).mean()
    return (means * length)[kept]
