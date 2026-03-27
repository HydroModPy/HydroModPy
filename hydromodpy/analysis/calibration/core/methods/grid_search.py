"""Exhaustive grid-search calibration method."""

from __future__ import annotations

from itertools import product

import numpy as np

from hydromodpy.analysis.calibration.core.results import CalibrationResults


def _normalize_bounds(bounds):
    """Normalize bounds to float arrays `(lower, upper)`."""
    bounds_list = [(float(lo), float(hi)) for lo, hi in bounds]
    lower = np.array([b[0] for b in bounds_list], dtype=float)
    upper = np.array([b[1] for b in bounds_list], dtype=float)
    if np.any(lower >= upper):
        raise ValueError("Each bound must satisfy lower < upper")
    return lower, upper


def grid_search_calibrate(objective_cost, bounds, n_per_dim=40, log_scale_indices=None):
    """
    Brute-force grid search (global, robust, potentially expensive).
    """
    lower, upper = _normalize_bounds(bounds)
    n_dim = len(lower)
    log_scale_indices = set() if log_scale_indices is None else set(log_scale_indices)

    if np.isscalar(n_per_dim):
        n_points = [int(n_per_dim)] * n_dim
    else:
        n_points = [int(v) for v in n_per_dim]
        if len(n_points) != n_dim:
            raise ValueError("n_per_dim length must match parameter dimension")

    axes = []
    for i in range(n_dim):
        n_i = max(2, n_points[i])
        if i in log_scale_indices:
            if lower[i] <= 0 or upper[i] <= 0:
                raise ValueError("Log-scale bounds must be strictly positive")
            axis = np.logspace(np.log10(lower[i]), np.log10(upper[i]), n_i)
        else:
            axis = np.linspace(lower[i], upper[i], n_i)
        axes.append(axis)

    best_cost = np.inf
    best_x = None
    eval_count = 0

    for values in product(*axes):
        x = np.array(values, dtype=float)
        cost = float(objective_cost(x))
        eval_count += 1
        if cost < best_cost:
            best_cost = cost
            best_x = x.copy()

    return CalibrationResults(
        method="grid_search",
        x_best=best_x,
        params_best=None,
        cost_best=best_cost,
        score_best=None,
        n_evaluations=eval_count,
    )

