"""Random-search calibration method."""

from __future__ import annotations

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


def random_search_calibrate(objective_cost, bounds, n_samples=6000, seed=42, log_scale_indices=None):
    """
    Random search (global, simple, easy to parallelize).
    """
    lower, upper = _normalize_bounds(bounds)
    n_dim = len(lower)
    log_scale_indices = set() if log_scale_indices is None else set(log_scale_indices)

    rng = np.random.default_rng(seed)

    n_samples = int(n_samples)
    samples = np.empty((n_samples, n_dim), dtype=float)
    for i in range(n_dim):
        if i in log_scale_indices:
            if lower[i] <= 0 or upper[i] <= 0:
                raise ValueError("Log-scale bounds must be strictly positive")
            log_vals = rng.uniform(np.log10(lower[i]), np.log10(upper[i]), n_samples)
            samples[:, i] = np.power(10.0, log_vals)
        else:
            samples[:, i] = rng.uniform(lower[i], upper[i], n_samples)

    best_cost = np.inf
    best_x = None
    for x in samples:
        cost = float(objective_cost(x))
        if cost < best_cost:
            best_cost = cost
            best_x = x.copy()

    return CalibrationResults(
        method="random_search",
        x_best=best_x,
        params_best=None,
        cost_best=best_cost,
        score_best=None,
        n_evaluations=n_samples,
    )

