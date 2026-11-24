"""Hydrological efficiency and error metrics.

Pure NumPy functions consumed by calibration, comparison, and display. All
metrics drop NaN-aligned pairs and return ``float`` (not ``np.float64``) so
they round-trip cleanly through JSON and DuckDB.

References
----------
- Nash, J. E., Sutcliffe, J. V. (1970). Journal of Hydrology, 10(3), 282-290.
- Gupta, H. V., et al. (2009). Journal of Hydrology, 377(1-2), 80-91.
- Moriasi, D. N., et al. (2007). Trans. ASABE, 50(3), 885-900. (PBIAS, with the
  opposite sign: here ``pbias`` has the sign of ``bias``, positive = overestimation)

A caller runs ``align`` first, which drops the pairs with NaN, then ``nse``,
``log_nse``, ``kge``, ``rmse``, ``mae``, ``bias``, ``pbias``, ``correlation``, or the
variants ``nse_delta``, ``kge_delta`` and ``nse_seasonal``, or the baseflow index
signatures ``bfi_gap`` and ``bfi_error``. A new metric goes here in
NumPy only, a float out, and its name is a row of ``metric_table.py``.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any

import numpy as np

from hydromodpy.core.scoring.baseflow import baseflow_indices

LOG_FLOOR_FRACTION = 0.01
"""Share of the median positive observation that ``log_floor`` offsets by."""

SPREAD_FLOOR = 1e-12
"""Spread, as a share of the largest observed magnitude, below which there is none.

The spread is the root mean square of the deviations an efficiency divides by.
A constant series has a mean that is not exactly its value in floating point,
so its deviations are rounding noise and not zeros, and an efficiency divided
by them is a huge finite number instead of NaN.
"""

__all__ = [
    "CYCLE_DAYS",
    "DATED_KERNELS",
    "RESERVOIR_INCREMENT_DAYS",
    "bfi_error_on_dates",
    "bfi_gap_on_dates",
    "delta_on_dates",
    "reservoir_on_dates",
    "sample_positions",
    "seasonal_on_dates",
    "kge_delta",
    "nse_delta",
    "nse_seasonal",
    "align",
    "bias",
    "clip_negatives",
    "correlation",
    "kge",
    "log_floor",
    "log_nse",
    "mae",
    "nse",
    "pbias",
    "rmse",
]


def align(sim, obs) -> tuple[np.ndarray, np.ndarray]:
    """Drop entries where either ``sim`` or ``obs`` is NaN.

    Returns flat float arrays (possibly empty when no overlap exists). Raises
    :class:`ValueError` if the two inputs have different shapes.
    """
    s = np.asarray(sim, dtype=float).ravel()
    o = np.asarray(obs, dtype=float).ravel()
    if s.shape != o.shape:
        raise ValueError(f"shape mismatch: sim={s.shape} obs={o.shape}")
    mask = np.isfinite(s) & np.isfinite(o)
    return s[mask], o[mask]


def nse(sim, obs) -> float:
    """Nash-Sutcliffe Efficiency.

        NSE = 1 - Σ(sim - obs)² / Σ(obs - mean(obs))²

    Returns NaN if ``obs`` is constant: its spread is no larger than rounding
    (:data:`SPREAD_FLOOR`).
    """
    s, o = align(sim, obs)
    if s.size == 0:
        return float("nan")
    denom = float(np.sum((o - o.mean()) ** 2))
    if _no_spread(denom, o.size, o):
        return float("nan")
    return float(1.0 - float(np.sum((s - o) ** 2)) / denom)


def _no_spread(sum_of_squares: float, n: int, observed) -> bool:
    """Whether ``n`` deviations of ``observed`` summing to ``sum_of_squares`` are rounding.

    ``observed`` gives the magnitude the spread is compared to; its NaN entries
    are ignored.
    """
    values = np.asarray(observed, dtype=float).ravel()
    values = values[np.isfinite(values)]
    magnitude = float(np.max(np.abs(values))) if values.size else 0.0
    return sum_of_squares <= n * (SPREAD_FLOOR * magnitude) ** 2


def log_floor(observed) -> float:
    """Offset added before the logarithm of a log-scale score.

    The larger of ``1e-9`` and ``0.01 × median(observed > 0)``, taken on the
    sample the score reads: the observations paired with a simulated value,
    inside the scoring window. NaN entries are ignored. With no positive
    observation the median counts as 1.
    """
    values = np.asarray(observed, dtype=float).ravel()
    positives = values[np.isfinite(values) & (values > 0.0)]
    median = float(np.median(positives)) if positives.size else 1.0
    return max(1e-9, LOG_FLOOR_FRACTION * median)


def clip_negatives(sim, obs) -> tuple[np.ndarray, np.ndarray, int]:
    """Clip the negative values of both series to zero and count them.

    The rule of every log-scale score: a discharge reconstructed below a dam
    can hold a few negative values, which a logarithm cannot take. The count
    is returned so a caller can report it, because a clipping that passes
    unnoticed hides a sign error in a reconstruction. NaN entries are not
    counted.
    """
    s = np.asarray(sim, dtype=float)
    o = np.asarray(obs, dtype=float)
    n_clipped = int(np.count_nonzero(s < 0.0) + np.count_nonzero(o < 0.0))
    if n_clipped == 0:
        return s, o, 0
    return np.clip(s, 0.0, None), np.clip(o, 0.0, None), n_clipped


def log_nse(sim, obs, *, eps: float | None = None) -> float:
    """NSE on log-transformed series; negative values are clipped to zero.

    The clipping is :func:`clip_negatives`; use it directly to learn how many
    values were clipped. When ``eps`` is None, the offset of :func:`log_floor`
    is used, read on the clipped observations, so the metric stays
    scale-invariant.
    """
    s, o = align(sim, obs)
    if s.size == 0:
        return float("nan")
    s, o, _ = clip_negatives(s, o)
    if eps is None:
        eps = log_floor(o)
    return nse(np.log(s + eps), np.log(o + eps))


def kge(sim, obs) -> dict[str, float]:
    """Kling-Gupta Efficiency, 2009 form (Gupta et al.), and its decomposition.

        KGE = 1 - sqrt((r - 1)² + (alpha - 1)² + (beta - 1)²)

    ``r`` is the Pearson correlation, ``alpha = std(sim) / std(obs)`` and
    ``beta = sum(sim) / sum(obs)``, the ratio of the means. The 2012 form
    (Kling et al.) takes ``alpha`` as a ratio of coefficients of variation
    and gives another number on the same series; it is not offered.

    Returns ``{"kge", "r", "alpha", "beta"}``.
    """
    s, o = align(sim, obs)
    nan = float("nan")
    reason = None
    if s.size < 2:
        reason = "fewer than 2 paired samples"
    else:
        std_o = float(np.std(o, ddof=0))
        sum_o = float(np.sum(o))
        if std_o == 0:
            reason = "the observations are constant, so alpha divides by zero"
        elif sum_o == 0:
            reason = "the observations sum to zero, so beta divides by zero"
        elif float(np.std(s, ddof=0)) == 0:
            reason = "the simulation is constant, so r is undefined"
    if reason is not None:
        warnings.warn(f"kge is NaN: {reason}.", UserWarning, stacklevel=2)
        return {"kge": nan, "r": nan, "alpha": nan, "beta": nan}
    r = float(np.corrcoef(s, o)[0, 1])
    alpha = float(np.std(s, ddof=0) / std_o)
    beta = float(np.sum(s) / sum_o)
    score = float(1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))
    return {"kge": score, "r": r, "alpha": alpha, "beta": beta}


def rmse(sim, obs) -> float:
    """Root-mean-square error."""
    s, o = align(sim, obs)
    if s.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean((s - o) ** 2)))


def mae(sim, obs) -> float:
    """Mean absolute error."""
    s, o = align(sim, obs)
    if s.size == 0:
        return float("nan")
    return float(np.mean(np.abs(s - o)))


def bias(sim, obs) -> float:
    """Mean signed error (sim - obs)."""
    s, o = align(sim, obs)
    if s.size == 0:
        return float("nan")
    return float(np.mean(s - o))


def pbias(sim, obs) -> float:
    """Percent bias: 100 × Σ(sim - obs) / Σ(obs).

    Same sign as :func:`bias`: positive means the model overestimates. This
    is the opposite of Moriasi et al. (2007), who write Σ(obs - sim); their
    scale, |PBIAS| < 10 % "very good", applies to the magnitude.
    """
    s, o = align(sim, obs)
    if s.size == 0:
        return float("nan")
    denom = float(np.sum(o))
    if denom == 0:
        return float("nan")
    return float(100.0 * float(np.sum(s - o)) / denom)


def correlation(sim, obs) -> float:
    """Pearson correlation coefficient."""
    s, o = align(sim, obs)
    if s.size < 2:
        return float("nan")
    if float(np.std(s)) == 0 or float(np.std(o)) == 0:
        return float("nan")
    return float(np.corrcoef(s, o)[0, 1])


GAP_SAMPLES: float = 1.5
"""Spacing, in samples, beyond which two neighbors lie on either side of a gap."""


def _align_on_time(sim, obs, times) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Drop the NaN pairs of ``sim`` and ``obs``, and their positions in time.

    ``times`` is the position of each sample on the time axis, counted in
    samples of the series. ``None`` reads the vector as a regular series:
    position ``i`` for entry ``i``, so a NaN left in place stays a gap.
    """
    s = np.asarray(sim, dtype=float).ravel()
    o = np.asarray(obs, dtype=float).ravel()
    if s.shape != o.shape:
        raise ValueError(f"shape mismatch: sim={s.shape} obs={o.shape}")
    t = np.arange(s.size, dtype=float) if times is None else np.asarray(times, dtype=float).ravel()
    if t.shape != s.shape:
        raise ValueError(f"shape mismatch: times={t.shape} sim={s.shape}")
    mask = np.isfinite(s) & np.isfinite(o) & np.isfinite(t)
    return s[mask], o[mask], t[mask]


def _increments(
    sim: np.ndarray, obs: np.ndarray, step: int, times=None
) -> tuple[np.ndarray, np.ndarray]:
    """Increments over ``step`` samples, i.e. ``x[i + step] - x[i]``.

    ``step`` is a TOLERANCE, not a smoothing: a day-to-day increment (``step = 1``)
    is destroyed by a two or three day phase shift even when the model reproduces
    the filling and emptying correctly, which over-penalizes a reservoir whose
    timing is right to within a few days. Differencing over a longer window keeps
    the flux signal while making a small shift a minor perturbation instead of a
    sign flip.

    An increment never spans a gap of the time axis (``times``, see
    :func:`_align_on_time`), nor a step back to an earlier date where a second
    series starts: each run of contiguous samples is differenced on its own.
    """
    sim, obs, t = _align_on_time(sim, obs, times)
    step = max(1, int(step))
    spacing = np.diff(t)
    breaks = np.flatnonzero((spacing <= 0.0) | (spacing > GAP_SAMPLES)) + 1
    d_sim: list[np.ndarray] = []
    d_obs: list[np.ndarray] = []
    for s_run, o_run in zip(np.split(sim, breaks), np.split(obs, breaks), strict=True):
        if s_run.size > step:
            d_sim.append(s_run[step:] - s_run[:-step])
            d_obs.append(o_run[step:] - o_run[:-step])
    if sum(part.size for part in d_sim) < 2:
        return np.empty(0), np.empty(0)
    return np.concatenate(d_sim), np.concatenate(d_obs)


def nse_delta(sim: np.ndarray, obs: np.ndarray, *, step: int = 1, times=None) -> float:
    """Nash-Sutcliffe on the INCREMENTS rather than on the state itself.

    A reservoir level is an integral, so an efficiency computed on it is dominated
    by the seasonal cycle and forgives compensating flux errors: a level can score
    well while its own increments score near zero, i.e. the day-to-day dynamics are
    almost uncorrelated. Scoring the increments tests the water balance that
    produced the level instead of the level it happened to reach.

    Use it ALONGSIDE a level metric, never alone: an increment score is blind to
    the absolute stage, so a model offset by ten meters can still score perfectly.

    ``times`` places each sample on the time axis, in samples of the series
    (see :func:`_increments`).
    """
    d_sim, d_obs = _increments(sim, obs, step, times)
    if d_sim.size == 0:
        return float("nan")
    denominator = float(np.sum((d_obs - d_obs.mean()) ** 2))
    if _no_spread(denominator, d_obs.size, obs):
        return float("nan")
    return float(1.0 - np.sum((d_sim - d_obs) ** 2) / denominator)


def kge_delta(sim: np.ndarray, obs: np.ndarray, *, step: int = 1, times=None) -> dict[str, float]:
    """Kling-Gupta on the increments; see :func:`nse_delta` and :func:`_increments`."""
    d_sim, d_obs = _increments(sim, obs, step, times)
    if d_sim.size == 0:
        return {"kge": float("nan"), "r": float("nan"), "alpha": float("nan"), "beta": float("nan")}
    return kge(d_sim, d_obs)


def nse_seasonal(sim: np.ndarray, obs: np.ndarray, *, period: float = 365, times=None) -> float:
    """Efficiency against a SEASONAL benchmark instead of the observed mean.

    ``NSE`` compares a model to a flat mean, a weak benchmark for a strongly
    seasonal signal: a model that has merely learnt there is a summer and a winter
    already scores well. Here the benchmark is the seasonal cycle of the
    observations themselves, so the score only credits what the model explains
    BEYOND that cycle. Negative means worse than the seasonal cycle alone, which a
    level scoring comfortably against the flat mean can easily be.

    The cycle is a least-squares fit of the annual and semi-annual harmonics rather
    than a day-of-year average, for one practical reason: a positional day-of-year
    average assumes the series starts on day one of the cycle, so dropping a warm-up
    that is not a whole number of years shifts the benchmark out of phase and the
    score becomes meaningless. A harmonic fit recovers the phase from the data, so
    it is unaffected by where the series is cut.

    ``period`` is the cycle length in samples (365 for a daily series).
    ``times`` places each sample on the time axis, in the same samples; unset,
    entry ``i`` sits at ``i``. A record with a gap needs it, or the harmonics
    are fitted out of phase past the gap.
    """
    sim, obs, t = _align_on_time(sim, obs, times)
    if sim.size == 0:
        return float("nan")
    if sim.size < 2 * int(period):
        warnings.warn(
            f"nse_seasonal is NaN: it fits two harmonics and needs two cycles, "
            f"{2 * int(period)} samples, and the series holds {sim.size}.",
            UserWarning,
            stacklevel=2,
        )
        return float("nan")
    angle = 2.0 * np.pi * (t - t[0]) / float(period)
    design = np.column_stack(
        [
            np.ones_like(angle),
            np.cos(angle),
            np.sin(angle),
            np.cos(2.0 * angle),
            np.sin(2.0 * angle),
        ]
    )
    coefficients, *_ = np.linalg.lstsq(design, obs, rcond=None)
    benchmark = design @ coefficients
    denominator = float(np.sum((obs - benchmark) ** 2))
    if _no_spread(denominator, obs.size, obs):
        return float("nan")
    return float(1.0 - np.sum((sim - obs) ** 2) / denominator)


def bfi_gap(sim, obs, *, times_days=None) -> float:
    """Simulated minus observed baseflow index, Wallingford filter, over the same days.

    Positive: the simulated stream is fed more by its aquifer than the gauged one.
    The index is blind to volume and to timing (a simulated series twice the
    observed one scores 0), so it qualifies a fit and never replaces one. NaN unless
    the series is daily. ``times_days`` is the date of each sample in days.
    """
    simulated, observed = baseflow_indices(sim, obs, times_days=times_days)
    return float(simulated - observed)


def bfi_error(sim, obs, *, times_days=None) -> float:
    """The absolute value of :func:`bfi_gap`, a cost a calibration can minimize."""
    return float(abs(bfi_gap(sim, obs, times_days=times_days)))


RESERVOIR_INCREMENT_DAYS: float = 10.0
"""Window, in days, over which the reservoir score differences the level.

A day-to-day increment is wrecked by a two or three day phase shift even when the
filling and emptying are right. Ten days keeps the flux signal and makes such a
shift a perturbation rather than a sign flip. A coarser series differences one
sample to the next.
"""


CYCLE_DAYS: float = 365.25
"""Length of the seasonal cycle, in days."""


def _cycle_samples(sample_days: float | None) -> float:
    """Samples in one seasonal cycle. Without dates, the series is taken as daily."""
    if sample_days is None:
        return 365.0
    return CYCLE_DAYS / float(sample_days)


def _increment_samples(sample_days: float | None) -> int:
    """Samples in the increment window of the reservoir score."""
    if sample_days is None:
        return int(RESERVOIR_INCREMENT_DAYS)
    return max(1, round(RESERVOIR_INCREMENT_DAYS / float(sample_days)))


def sample_positions(times_days: Any, sample_days: float | None) -> np.ndarray | None:
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


def seasonal_on_dates(
    sim: np.ndarray,
    obs: np.ndarray,
    *,
    sample_days: float | None = None,
    times_days: Any = None,
) -> float:
    """``nse_seasonal`` with a cycle of one year of the series' own samples."""
    return nse_seasonal(
        sim,
        obs,
        period=_cycle_samples(sample_days),
        times=sample_positions(times_days, sample_days),
    )


def delta_on_dates(
    sim: np.ndarray,
    obs: np.ndarray,
    *,
    sample_days: float | None = None,
    times_days: Any = None,
) -> float:
    """``nse_delta`` from one sample to the next, never across a gap of the dates."""
    return nse_delta(sim, obs, times=sample_positions(times_days, sample_days))


def reservoir_on_dates(
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
    seasonal = seasonal_on_dates(sim, obs, sample_days=sample_days, times_days=times_days)
    increments = nse_delta(
        sim,
        obs,
        step=_increment_samples(sample_days),
        times=sample_positions(times_days, sample_days),
    )
    if not np.isfinite(seasonal) or not np.isfinite(increments):
        return float("nan")
    return 0.5 * float(seasonal) + 0.5 * float(increments)


def _days_of(sim: np.ndarray, sample_days: float | None, times_days: Any) -> Any:
    """The dates of the samples; evenly spaced by ``sample_days`` when only that is known."""
    if times_days is None and sample_days is not None:
        return np.arange(np.asarray(sim).size, dtype=float) * float(sample_days)
    return times_days


def bfi_gap_on_dates(
    sim: np.ndarray,
    obs: np.ndarray,
    *,
    sample_days: float | None = None,
    times_days: Any = None,
) -> float:
    """``bfi_gap`` on the dates of the series; NaN on a step coarser than a day."""
    return bfi_gap(sim, obs, times_days=_days_of(sim, sample_days, times_days))


def bfi_error_on_dates(
    sim: np.ndarray,
    obs: np.ndarray,
    *,
    sample_days: float | None = None,
    times_days: Any = None,
) -> float:
    """``bfi_error`` on the dates of the series; NaN on a step coarser than a day."""
    return bfi_error(sim, obs, times_days=_days_of(sim, sample_days, times_days))


DATED_KERNELS: dict[str, Callable[..., float]] = {
    "nse_delta": delta_on_dates,
    "nse_seasonal": seasonal_on_dates,
    "reservoir": reservoir_on_dates,
    "bfi_gap": bfi_gap_on_dates,
    "bfi_error": bfi_error_on_dates,
}
"""Kernels that read the dates of the samples, by metric name.

Each takes ``sample_days``, the step of the series, and ``times_days``, the date of
each sample in days. A year, a window and a gap are counted from them, so a monthly
series holds them in fewer samples than a daily one.
"""
