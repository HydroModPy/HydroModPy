"""Lightweight diagnostics helpers for calibration iteration traces.

Consumes a list-of-dicts or a ``pd.DataFrame`` matching the
``calibration_iterations`` schema. Parameter columns may be flat (one
column per parameter) or nested under a single ``parameters`` dict column.
Depends only on numpy and pandas.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import numpy as np
import pandas as pd

_META_COLUMNS: frozenset[str] = frozenset(
    {
        "iter",
        "iteration",
        "i",
        "session_id",
        "sim_id",
        "params_hash",
        "status",
        "from_cache",
        "duration_s",
        "components",
        "parameters",
        "cost",
        "case_cost",
        "case_id",
        "case_status",
        "site",
        "rel_dir",
        "phase",
        "restart",
        "trial",
        "speculative_unused",
        "objective",
    }
)


def iterations_to_dataframe(iterations: Iterable[Mapping[str, Any]] | pd.DataFrame) -> pd.DataFrame:
    """Return a flat DataFrame with nested ``parameters`` dicts expanded."""
    df = (
        iterations.copy()
        if isinstance(iterations, pd.DataFrame)
        else pd.DataFrame(list(iterations))
    )
    if df.empty or "parameters" not in df.columns:
        return df
    nested = df["parameters"].apply(lambda v: v if isinstance(v, Mapping) else {})
    expanded = pd.json_normalize(nested)
    for col in expanded.columns:
        if col not in df.columns:
            df[col] = expanded[col].values
    return df


def convergence_rate(
    iterations: Iterable[Mapping[str, Any]] | pd.DataFrame,
    *,
    objective: str = "cost",
) -> dict[str, float]:
    """Least-squares slope of best-so-far improvement vs. iteration.

    Returns ``slope`` (positive = improving), ``intercept``, ``r_squared``
    and ``n_points``. Traces with <2 finite values yield NaN fields.
    """
    df = iterations_to_dataframe(iterations)
    col = objective if objective in df.columns else "objective"
    y = np.asarray(df.get(col, pd.Series(dtype=float)), dtype=float).ravel()
    y = y[np.isfinite(y)]
    if y.size < 2:
        return {
            "slope": float("nan"),
            "intercept": float("nan"),
            "r_squared": float("nan"),
            "n_points": float(y.size),
        }
    best = np.minimum.accumulate(y)
    improvement = best[0] - best
    x = np.arange(improvement.size, dtype=float)
    slope, intercept = np.polyfit(x, improvement, 1)
    residuals = improvement - (slope * x + intercept)
    ss_res = float(np.sum(residuals**2))
    ss_tot = float(np.sum((improvement - float(np.mean(improvement))) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0.0 else float("nan")
    return {
        "slope": float(slope),
        "intercept": float(intercept),
        "r_squared": float(r_squared),
        "n_points": float(improvement.size),
    }


MIN_TRIALS_FOR_A_CORRELATION = 6
"""Below six points, independent values reach ``|r| >= 0.8`` more than one time in ten.

Two points always give ``+1`` or ``-1``, and a margin can leave that few."""


def parameter_correlation(
    iterations: Iterable[Mapping[str, Any]] | pd.DataFrame,
    parameters: Iterable[str] | None = None,
    *,
    below_cost: float | None = None,
) -> pd.DataFrame:
    """Pearson correlation matrix over calibrated parameter columns.

    When ``parameters`` is ``None``, all non-meta columns are used.
    ``below_cost`` keeps the trials whose ``cost`` is at or under it. Over all
    trials a coefficient describes the placement of the search, and it is zero by
    construction on a grid. Over the trials that nearly match the best, it shows
    a ridge. Too few trials (:data:`MIN_TRIALS_FOR_A_CORRELATION`) yield an
    all-NaN square frame.
    """
    df = iterations_to_dataframe(iterations)
    if below_cost is not None:
        df = df[pd.to_numeric(df["cost"], errors="coerce") <= below_cost]
    if parameters is None:
        parameters = [c for c in df.columns if c not in _META_COLUMNS]
    names = [str(n) for n in parameters]
    if not names:
        return pd.DataFrame()
    sub = df.reindex(columns=names).apply(pd.to_numeric, errors="coerce")
    if len(sub) < MIN_TRIALS_FOR_A_CORRELATION:
        return pd.DataFrame(np.full((len(names), len(names)), np.nan), index=names, columns=names)
    return sub.corr(method="pearson")


MIN_RIDGE_POINTS = 5
"""Fewest points of the best fifth a ridge reading needs."""
RIDGE_SHARE = 0.2
"""Share of the trials, the lowest costs, that makes the cloud read for a ridge."""
RIDGE_EIGEN_FLOOR = 1e-12
"""Smallest eigenvalue, relative to the largest, that still gives an axis ratio."""


def best_fifth_ridge(
    points: np.ndarray, costs: np.ndarray, names: list[str]
) -> dict[str, Any] | None:
    """Read a ridge in the cloud of the best fifth of the trials of a fixed plan.

    ``points`` holds one row per trial and one column per parameter, in search space
    scaled to the unit box, so that a decade of K and a share of porosity weigh the same.
    The best fifth (at least :data:`MIN_RIDGE_POINTS`) gives the Spearman correlation
    of each pair, and ``axis_ratio``, the square root of the ratio of the largest to the
    smallest eigenvalue of its covariance. A ratio near one is a round cloud, a large one a
    ridge. Returns None for fewer points, one parameter, or a value that is not finite.
    """
    ok = np.isfinite(costs) & np.isfinite(points).all(axis=1)
    cost, cloud = costs[ok], points[ok]
    count = max(MIN_RIDGE_POINTS, int(np.ceil(RIDGE_SHARE * len(cost))))
    if len(names) < 2 or len(cost) < count:
        return None
    cloud = cloud[np.argsort(cost, kind="stable")[:count]]
    frame = pd.DataFrame(cloud, columns=names)
    ranks = frame.corr(method="spearman")
    pairs = [
        (a, b, float(ranks.at[a, b]))
        for i, a in enumerate(names)
        for b in names[i + 1 :]
        if np.isfinite(ranks.at[a, b])
    ]
    eigen = np.linalg.eigvalsh(np.atleast_2d(np.cov(cloud, rowvar=False)))
    found: dict[str, Any] = {"n_points": count, "n_trials": int(len(cost)), "spearman": pairs}
    # Fewer points than parameters leave a flat axis: the ratio would be noise.
    if count > len(names) and np.isfinite(eigen).all() and eigen[0] > RIDGE_EIGEN_FLOOR * eigen[-1]:
        found["axis_ratio"] = float(np.sqrt(eigen[-1] / eigen[0]))
    return found


DEFAULT_CORRELATION_THRESHOLD = 0.8


def correlated_parameter_pairs(
    iterations: Iterable[Mapping[str, Any]] | pd.DataFrame,
    parameters: Iterable[str] | None = None,
    *,
    threshold: float = DEFAULT_CORRELATION_THRESHOLD,
    below_cost: float | None = None,
) -> list[tuple[str, str, float]]:
    """Pairs whose correlation over the trace exceeds ``threshold``, worst first.

    A calibration reports one value per parameter and, on its own, says nothing
    about whether the data could tell two of them apart. A pair that moved
    together across the whole search to hold the same cost was not identified:
    the search stopped on a ridge and reported that point as a minimum. The sign
    is kept because it says which way the trade-off went. ``below_cost`` is read
    as in :func:`parameter_correlation`.
    """
    matrix = parameter_correlation(iterations, parameters, below_cost=below_cost)
    if matrix.empty:
        return []
    names = [str(n) for n in matrix.columns]
    found: list[tuple[str, str, float]] = []
    for i, first in enumerate(names):
        for second in names[i + 1 :]:
            coefficient = matrix.at[first, second]
            if pd.isna(coefficient) or abs(float(coefficient)) < threshold:
                continue
            found.append((first, second, float(coefficient)))
    found.sort(key=lambda pair: abs(pair[2]), reverse=True)
    return found


__all__ = [
    "MIN_RIDGE_POINTS",
    "best_fifth_ridge",
    "DEFAULT_CORRELATION_THRESHOLD",
    "convergence_rate",
    "correlated_parameter_pairs",
    "iterations_to_dataframe",
    "parameter_correlation",
]
