"""Hydrological efficiency and error metrics.

Pure NumPy functions consumed by calibration, comparison, and display. All
metrics drop NaN-aligned pairs and return ``float`` (not ``np.float64``) so
they round-trip cleanly through JSON and DuckDB.

References
----------
- Nash, J. E., Sutcliffe, J. V. (1970). Journal of Hydrology, 10(3), 282-290.
- Gupta, H. V., et al. (2009). Journal of Hydrology, 377(1-2), 80-91.
- Moriasi, D. N., et al. (2007). Trans. ASABE, 50(3), 885-900. (PBIAS)
"""

from __future__ import annotations

import numpy as np

LOG_FLOOR_FRACTION = 0.01
"""Share of the median positive observation that ``log_floor`` offsets by."""

__all__ = [
    "kge_delta",
    "nse_delta",
    "nse_seasonal",
    "align",
    "bias",
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

    Returns NaN if ``obs`` is constant (denominator vanishes).
    """
    s, o = align(sim, obs)
    if s.size == 0:
        return float("nan")
    denom = float(np.sum((o - o.mean()) ** 2))
    if denom <= 0.0:
        return float("nan")
    return float(1.0 - float(np.sum((s - o) ** 2)) / denom)


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


def log_nse(sim, obs, *, eps: float | None = None) -> float:
    """NSE on log-transformed series; rejects negative values.

    When ``eps`` is None, the offset of :func:`log_floor` is used, so the
    metric stays scale-invariant.
    """
    s, o = align(sim, obs)
    if s.size == 0:
        return float("nan")
    if np.any(s < 0) or np.any(o < 0):
        raise ValueError("log_nse: series contain negative values")
    if eps is None:
        eps = log_floor(o)
    return nse(np.log(s + eps), np.log(o + eps))


def kge(sim, obs) -> dict[str, float]:
    """Kling-Gupta Efficiency (2009) and its decomposition.

    Returns ``{"kge", "r", "alpha", "beta"}``.
    """
    s, o = align(sim, obs)
    nan = float("nan")
    if s.size < 2:
        return {"kge": nan, "r": nan, "alpha": nan, "beta": nan}
    std_o = float(np.std(o, ddof=0))
    sum_o = float(np.sum(o))
    if std_o == 0 or sum_o == 0:
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
    """Percent bias: 100 × Σ(obs - sim) / Σ(obs).

    Positive values indicate model underestimation. |PBIAS| < 10 % is
    considered "very good" by Moriasi et al. (2007).
    """
    s, o = align(sim, obs)
    if s.size == 0:
        return float("nan")
    denom = float(np.sum(o))
    if denom == 0:
        return float("nan")
    return float(100.0 * float(np.sum(o - s)) / denom)


def correlation(sim, obs) -> float:
    """Pearson correlation coefficient."""
    s, o = align(sim, obs)
    if s.size < 2:
        return float("nan")
    if float(np.std(s)) == 0 or float(np.std(o)) == 0:
        return float("nan")
    return float(np.corrcoef(s, o)[0, 1])


GAP_SAMPLES: float = 1.5
"""Spacing, in samples, beyond which two neighbours lie on either side of a gap."""


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
    the filling and emptying correctly, which over-penalises a reservoir whose
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
    the absolute stage, so a model offset by ten metres can still score perfectly.

    ``times`` places each sample on the time axis, in samples of the series
    (see :func:`_increments`).
    """
    d_sim, d_obs = _increments(sim, obs, step, times)
    if d_sim.size == 0:
        return float("nan")
    denominator = float(np.sum((d_obs - d_obs.mean()) ** 2))
    if denominator <= 0.0:
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
    if sim.size == 0 or sim.size < 2 * int(period):
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
    if denominator <= 0.0:
        return float("nan")
    return float(1.0 - np.sum((sim - obs) ** 2) / denominator)
