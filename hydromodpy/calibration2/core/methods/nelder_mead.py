"""Nelder-Mead local calibration method."""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration2.core.results import CalibrationResults

try:
    from scipy import optimize as scipy_optimize
except Exception:  # pragma: no cover - depends on local env
    scipy_optimize = None


def _normalize_bounds(bounds):
    """Normalize bounds to float arrays `(lower, upper)`."""
    bounds_list = [(float(lo), float(hi)) for lo, hi in bounds]
    lower = np.array([b[0] for b in bounds_list], dtype=float)
    upper = np.array([b[1] for b in bounds_list], dtype=float)
    if np.any(lower >= upper):
        raise ValueError("Each bound must satisfy lower < upper")
    return lower, upper


def _clip_to_bounds(x, lower, upper):
    """Clip a parameter vector to valid bounds."""
    return np.minimum(np.maximum(x, lower), upper)


def _build_penalized_cost(objective_cost, lower, upper, penalty_weight=1e4):
    """Build a bound-aware cost wrapper for unconstrained local methods."""

    def _penalized_cost(x):
        x = np.asarray(x, dtype=float)
        under = np.maximum(lower - x, 0.0)
        over = np.maximum(x - upper, 0.0)
        penalty = 0.0
        if np.any(under > 0.0) or np.any(over > 0.0):
            penalty = float(penalty_weight) * float(np.sum(under**2 + over**2))
        x_in = _clip_to_bounds(x, lower, upper)
        return float(objective_cost(x_in) + penalty)

    return _penalized_cost


def nelder_mead_calibrate(objective_cost, bounds, x0=None, max_iter=1200):
    """
    Local derivative-free calibration using Nelder-Mead (SciPy).
    """
    if scipy_optimize is None:
        raise ImportError("scipy is required for nelder_mead_calibrate")

    lower, upper = _normalize_bounds(bounds)
    n_dim = len(lower)
    if x0 is None:
        x0 = np.array([0.5 * (lower[i] + upper[i]) for i in range(n_dim)], dtype=float)
    else:
        x0 = _clip_to_bounds(np.asarray(x0, dtype=float), lower, upper)

    penalized_cost = _build_penalized_cost(
        objective_cost=objective_cost,
        lower=lower,
        upper=upper,
        penalty_weight=1e4,
    )

    result = scipy_optimize.minimize(
        penalized_cost,
        x0,
        method="Nelder-Mead",
        options={"maxiter": int(max_iter), "xatol": 1e-10, "fatol": 1e-10},
    )

    x_best = _clip_to_bounds(result.x, lower, upper)
    cost_best = float(objective_cost(x_best))

    return CalibrationResults(
        method="nelder_mead",
        x_best=x_best,
        params_best=None,
        cost_best=cost_best,
        score_best=None,
        n_evaluations=int(result.nfev),
        metadata={
            "success": bool(result.success),
            "message": str(result.message),
        },
    )
