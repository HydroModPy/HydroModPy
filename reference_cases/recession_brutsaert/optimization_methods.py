"""
Optimization algorithms used by calibration workflows.

Implemented families:
- grid search: exhaustive global scan of a discretized parameter space,
- random search: global Monte Carlo sampling in bounded space,
- Nelder-Mead: local simplex-based search via `scipy.optimize.minimize`,
- simplex (classic): local simplex-based search via `scipy.optimize.fmin`.
"""

from itertools import product

import numpy as np

try:
    from scipy import optimize as scipy_optimize
except Exception:  # pragma: no cover - depends on local env
    scipy_optimize = None


def _normalize_bounds(bounds):
    """
    Normalize bounds to float arrays `(lower, upper)` for any dimension.

    Parameters
    ----------
    bounds : sequence[(low, high)]
        Bounds provided in optimizer-agnostic format.

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        Lower and upper bound vectors with identical shape.
    """
    bounds_list = [(float(lo), float(hi)) for lo, hi in bounds]
    lower = np.array([b[0] for b in bounds_list], dtype=float)
    upper = np.array([b[1] for b in bounds_list], dtype=float)
    if np.any(lower >= upper):
        raise ValueError("Each bound must satisfy lower < upper")
    return lower, upper


def _clip_to_bounds(x, lower, upper):
    """
    Clip a parameter vector to valid bounds.

    This helper is used to keep local optimizers numerically stable when they
    temporarily propose values outside the feasible hyper-rectangle.
    """
    return np.minimum(np.maximum(x, lower), upper)


def _build_penalized_cost(objective_cost, lower, upper, penalty_weight=1e4):
    """
    Build a bound-aware cost wrapper for unconstrained local optimizers.

    Parameters
    ----------
    objective_cost : callable
        Original cost function defined on feasible parameters.
    lower : np.ndarray
        Lower parameter bounds.
    upper : np.ndarray
        Upper parameter bounds.
    penalty_weight : float
        Quadratic penalty multiplier for out-of-bound proposals.

    Returns
    -------
    callable
        Penalized callable that can safely be evaluated on unconstrained points.

    Notes
    -----
    For a trial vector `x`:
    1. A quadratic penalty is added for each bound violation.
    2. The original objective is evaluated on the clipped feasible vector.
    """

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


def grid_search_optimize(objective_cost, bounds, n_per_dim=40, log_scale_indices=None):
    """
    Brute-force grid search (global, robust, potentially expensive).

    Parameters
    ----------
    objective_cost : callable
        Cost function expecting an array-like parameter vector.
    bounds : sequence[(low, high)]
        Parameter bounds.
    n_per_dim : int or sequence[int]
        Number of grid points per dimension.
    log_scale_indices : iterable[int] or None
        Dimensions sampled with log spacing.

    Returns
    -------
    dict
        Best solution and metadata:
        `method`, `x_best`, `cost_best`, `n_evaluations`.

    Algorithm
    ---------
    1. Build one axis per parameter between lower/upper bounds.
    2. Optionally sample selected axes in log space.
    3. Evaluate all combinations (Cartesian product).
    4. Keep parameter vector with minimum cost.

    Tradeoffs
    ---------
    - Very robust and deterministic.
    - Cost grows exponentially with dimension.
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
            # Log spacing is useful for parameters spanning multiple orders of
            # magnitude (e.g. hydraulic conductivity K).
            axis = np.logspace(np.log10(lower[i]), np.log10(upper[i]), n_i)
        else:
            axis = np.linspace(lower[i], upper[i], n_i)
        axes.append(axis)

    best_cost = np.inf
    best_x = None
    eval_count = 0

    # Exhaustive Cartesian product over all parameter axes.
    for values in product(*axes):
        x = np.array(values, dtype=float)
        cost = float(objective_cost(x))
        eval_count += 1
        if cost < best_cost:
            best_cost = cost
            best_x = x.copy()

    return {
        "method": "grid_search",
        "x_best": best_x,
        "cost_best": best_cost,
        "n_evaluations": eval_count,
    }


def random_search_optimize(objective_cost, bounds, n_samples=6000, seed=42, log_scale_indices=None):
    """
    Random search (global, simple, easy to parallelize).

    `log_scale_indices` controls which dimensions are sampled log-uniformly.

    Returns
    -------
    dict
        Best solution and metadata:
        `method`, `x_best`, `cost_best`, `n_evaluations`.

    Algorithm
    ---------
    1. Draw `n_samples` points independently inside bounds.
    2. Use log-uniform sampling on selected dimensions if requested.
    3. Evaluate objective on all points.
    4. Return best sampled point.

    Tradeoffs
    ---------
    - Scales better than grid search in moderate/high dimension.
    - Stochastic; quality depends on sample count and seed.
    """
    lower, upper = _normalize_bounds(bounds)
    n_dim = len(lower)
    log_scale_indices = set() if log_scale_indices is None else set(log_scale_indices)

    # Use numpy Generator for reproducible Monte-Carlo style exploration.
    rng = np.random.default_rng(seed)

    samples = np.empty((int(n_samples), n_dim), dtype=float)
    for i in range(n_dim):
        if i in log_scale_indices:
            if lower[i] <= 0 or upper[i] <= 0:
                raise ValueError("Log-scale bounds must be strictly positive")
            log_vals = rng.uniform(np.log10(lower[i]), np.log10(upper[i]), int(n_samples))
            samples[:, i] = np.power(10.0, log_vals)
        else:
            samples[:, i] = rng.uniform(lower[i], upper[i], int(n_samples))

    best_cost = np.inf
    best_x = None

    # Keep only the best sample encountered so far.
    for x in samples:
        cost = float(objective_cost(x))
        if cost < best_cost:
            best_cost = cost
            best_x = x.copy()

    return {
        "method": "random_search",
        "x_best": best_x,
        "cost_best": best_cost,
        "n_evaluations": int(n_samples),
    }


def nelder_mead_optimize(objective_cost, bounds, x0=None, max_iter=1200):
    """
    Local derivative-free optimization using Nelder-Mead (SciPy).

    Notes
    -----
    Algorithm (simplex-based)
    -------------------------
    Nelder-Mead maintains a simplex of `n_dim + 1` points and iteratively
    applies reflection / expansion / contraction / shrink steps to move this
    simplex toward lower objective values.

    Bound handling
    --------------
    `scipy.optimize.minimize(method="Nelder-Mead")` is unconstrained here.
    We therefore optimize a penalized objective and clip points before true
    objective evaluation.

    Practical usage
    ---------------
    Best used as local refinement after a global initialization
    (grid search or random search).

    Returns
    -------
    dict
        Best solution and SciPy convergence metadata.
    """
    if scipy_optimize is None:
        raise ImportError("scipy is required for nelder_mead_optimize")

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
        # Tight tolerances are acceptable here because objective evaluation is
        # relatively cheap for this reference case.
        options={"maxiter": int(max_iter), "xatol": 1e-10, "fatol": 1e-10},
    )

    # Re-clip final parameters to ensure strict feasibility.
    x_best = _clip_to_bounds(result.x, lower, upper)
    cost_best = float(objective_cost(x_best))

    return {
        "method": "nelder_mead",
        "x_best": x_best,
        "cost_best": cost_best,
        "n_evaluations": int(result.nfev),
        "success": bool(result.success),
        "message": str(result.message),
    }


def scipy_simplex_optimize(
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
    Classic simplex optimization via `scipy.optimize.fmin`.

    This function is an explicit example of using a standard Python package
    solver "as is" (SciPy), while keeping this project's output dictionary
    format and bound handling.

    Parameters
    ----------
    objective_cost : callable
        Cost function to minimize.
    bounds : sequence[(low, high)]
        Parameter bounds.
    x0 : array-like or None
        Initial parameter vector. If None, midpoint of bounds is used.
    max_iter : int
        Maximum simplex iterations.
    max_fun : int or None
        Maximum number of objective evaluations (`None` lets SciPy decide).
    xtol : float
        Convergence tolerance on parameters.
    ftol : float
        Convergence tolerance on objective value.
    disp : bool
        If True, let SciPy print convergence messages.

    Returns
    -------
    dict
        Best solution and convergence metadata:
        `method`, `x_best`, `cost_best`, `n_evaluations`, `n_iterations`,
        `success`, `message`.
    """
    if scipy_optimize is None:
        raise ImportError("scipy is required for scipy_simplex_optimize")

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

    return {
        "method": "simplex",
        "x_best": x_best,
        "cost_best": cost_best,
        "n_evaluations": int(n_func),
        "n_iterations": int(n_iter),
        "success": bool(success),
        "message": message,
    }


class OptimizationDispatcher:
    """
    Extensible optimization dispatcher based on a method registry.

    This class is the primary optimization API used by calibration code.
    It centralizes method routing and keeps extension simple via `register(...)`.

    Typical lifecycle:
    1. Build dispatcher with initial methods.
    2. Add/override methods with `register(...)`.
    3. Call `optimize(...)` with method name + common arguments.
    """

    def __init__(self, methods=None):
        """
        Initialize an optimization dispatcher with an optional method mapping.

        Parameters
        ----------
        methods : dict[str, callable] or None
            Optional initial registry where keys are method names and values
            are optimizer callables.
        """
        # Registry structure:
        #   canonical_method_name -> optimizer_callable
        self._methods = {}
        if methods is not None:
            # Register through the public method so validation is shared.
            for name, optimizer in methods.items():
                self.register(name, optimizer)

    @staticmethod
    def _normalize_method_name(method):
        """
        Convert a method identifier to a canonical lookup key.

        Normalization applies `str(...)`, trims spaces, and lowercases.
        """
        # Canonicalization avoids duplicate registrations caused by case/spacing.
        return str(method).strip().lower()

    def register(self, name, optimizer):
        """
        Register (or override) an optimization method.

        The optimizer callable must follow signature style:
        `optimizer(objective_cost, bounds, **kwargs) -> dict`.
        """
        key = self._normalize_method_name(name)
        if not key:
            raise ValueError("method name cannot be empty")
        if not callable(optimizer):
            raise TypeError("optimizer must be callable")
        # Overwrite is intentional: enables local experiments and hot-swapping.
        self._methods[key] = optimizer
        return self

    def available_methods(self):
        """
        Return currently registered optimization method names.

        Returns
        -------
        tuple[str, ...]
            Alphabetically sorted canonical method names.
        """
        # Sorted order makes logs/tests deterministic and easier to compare.
        return tuple(sorted(self._methods.keys()))

    def optimize(self, objective_cost, bounds, method="random_search", **kwargs):
        """
        Run optimization using the selected method from the registry.

        Parameters
        ----------
        objective_cost : callable
            Cost function to minimize.
        bounds : sequence[(low, high)]
            Parameter bounds.
        method : str
            Registered method name.
        """
        # 1) Normalize user-provided method key.
        key = self._normalize_method_name(method)
        # 2) Resolve callable in registry.
        optimizer = self._methods.get(key)
        if optimizer is None:
            available = ", ".join(self.available_methods()) or "<none>"
            raise ValueError(f"Unknown method '{method}'. Supported: {available}")
        # 3) Delegate optimization run to selected implementation.
        return optimizer(objective_cost=objective_cost, bounds=bounds, **kwargs)


DEFAULT_OPTIMIZATION_DISPATCHER = OptimizationDispatcher(
    methods={
        "grid_search": grid_search_optimize,
        "random_search": random_search_optimize,
        "nelder_mead": nelder_mead_optimize,
        "simplex": scipy_simplex_optimize,
    }
)
