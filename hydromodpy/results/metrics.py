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

__all__ = [
    "align",
    "bias",
    "correlation",
    "kge",
    "log_nse",
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


def log_nse(sim, obs, *, eps: float | None = None) -> float:
    """NSE on log-transformed series; rejects negative values.

    When ``eps`` is None, an offset of ``max(1e-9, 0.01 × median(obs > 0))``
    is used so the metric stays scale-invariant.
    """
    s, o = align(sim, obs)
    if s.size == 0:
        return float("nan")
    if np.any(s < 0) or np.any(o < 0):
        raise ValueError("log_nse: series contain negative values")
    if eps is None:
        positives = o[o > 0]
        med = float(np.median(positives)) if positives.size else 1.0
        eps = max(1e-9, 0.01 * med)
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
