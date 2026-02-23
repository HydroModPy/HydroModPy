"""Classic simplex calibration method (`scipy.optimize.fmin`)."""

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


def simplex_calibrate(
    objective_cost,
    bounds,
    x0=None,
    max_iter=1200,
    max_fun=None,
    xtol=1e-10,
    ftol=1e-10,
    disp=False,
):
    """
    Classic simplex calibration via `scipy.optimize.fmin`.
    """
    if scipy_optimize is None:
        raise ImportError("scipy is required for simplex_calibrate")

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

    fmin_kwargs = {
        "func": penalized_cost,
        "x0": x0,
        "xtol": float(xtol),
        "ftol": float(ftol),
        "maxiter": int(max_iter),
        "full_output": True,
        "disp": bool(disp),
        "retall": False,
    }
    if max_fun is not None:
        fmin_kwargs["maxfun"] = int(max_fun)

    x_raw, _, n_iter, n_func, warnflag = scipy_optimize.fmin(**fmin_kwargs)

    x_best = _clip_to_bounds(x_raw, lower, upper)
    cost_best = float(objective_cost(x_best))

    if warnflag == 0:
        message = "Optimization terminated successfully."
        success = True
    elif warnflag == 1:
        message = "Maximum number of function evaluations has been exceeded."
        success = False
    else:
        message = "Maximum number of iterations has been exceeded."
        success = False

    return CalibrationResults(
        method="simplex",
        x_best=x_best,
        params_best=None,
        cost_best=cost_best,
        score_best=None,
        n_evaluations=int(n_func),
        metadata={
            "n_iterations": int(n_iter),
            "success": bool(success),
            "message": message,
        },
    )
