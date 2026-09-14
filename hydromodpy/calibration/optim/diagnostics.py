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
        "metrics",
        "parameters",
        "objective_value",
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
    objective: str = "objective_value",
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


def parameter_correlation(
    iterations: Iterable[Mapping[str, Any]] | pd.DataFrame,
    parameters: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Pearson correlation matrix over calibrated parameter columns.

    When ``parameters`` is ``None``, all non-meta columns are used.
    Traces with <2 rows yield an all-NaN square frame.
    """
    df = iterations_to_dataframe(iterations)
    if parameters is None:
        parameters = [c for c in df.columns if c not in _META_COLUMNS]
    names = [str(n) for n in parameters]
    if not names:
        return pd.DataFrame()
    sub = df.reindex(columns=names).apply(pd.to_numeric, errors="coerce")
    if len(sub) < 2:
        return pd.DataFrame(np.full((len(names), len(names)), np.nan), index=names, columns=names)
    return sub.corr(method="pearson")


DEFAULT_CORRELATION_THRESHOLD = 0.8


def correlated_parameter_pairs(
    iterations: Iterable[Mapping[str, Any]] | pd.DataFrame,
    parameters: Iterable[str] | None = None,
    *,
    threshold: float = DEFAULT_CORRELATION_THRESHOLD,
) -> list[tuple[str, str, float]]:
    """Pairs whose correlation over the trace exceeds ``threshold``, worst first.

    A calibration reports one value per parameter and, on its own, says nothing
    about whether the data could tell two of them apart. A pair that moved
    together across the whole search to hold the same cost was not identified:
    the search stopped on a ridge and reported that point as a minimum. The sign
    is kept because it says which way the trade-off went.
    """
    matrix = parameter_correlation(iterations, parameters)
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
    "DEFAULT_CORRELATION_THRESHOLD",
    "convergence_rate",
    "correlated_parameter_pairs",
    "iterations_to_dataframe",
    "parameter_correlation",
]
