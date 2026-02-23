"""Objective-surface approximation helpers for 1D/2D calibration spaces."""

from __future__ import annotations

import warnings

import numpy as np

try:
    from scipy.stats import qmc as scipy_qmc
except Exception:  # pragma: no cover - depends on local env
    scipy_qmc = None

try:
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, RBF
except Exception:  # pragma: no cover - depends on local env
    ConvergenceWarning = None
    GaussianProcessRegressor = None
    ConstantKernel = None
    RBF = None


_SUPPORTED_SAMPLING = ("auto", "regular", "sobol", "lhs")
_SUPPORTED_INTERPOLATION = ("auto", "gp", "linear", "idw")


def _ordered_bounds(bounds, parameter_names):
    """Return lower/upper arrays in canonical parameter order."""
    names = tuple(str(name) for name in parameter_names)
    if len(names) == 0:
        raise ValueError("parameter_names cannot be empty")

    if isinstance(bounds, dict):
        missing = [name for name in names if name not in bounds]
        if missing:
            raise ValueError(f"Missing bounds for parameters: {missing}")
        lower = np.array([float(bounds[name][0]) for name in names], dtype=float)
        upper = np.array([float(bounds[name][1]) for name in names], dtype=float)
    else:
        pairs = np.asarray(list(bounds), dtype=float)
        if pairs.ndim != 2 or pairs.shape[1] != 2:
            raise ValueError("bounds must be a sequence of (low, high)")
        if pairs.shape[0] != len(names):
            raise ValueError(
                f"bounds size ({pairs.shape[0]}) must match parameter count ({len(names)})"
            )
        lower = pairs[:, 0].astype(float)
        upper = pairs[:, 1].astype(float)

    if np.any(lower >= upper):
        raise ValueError("Each bound must satisfy lower < upper")
    return lower, upper


def _normalize_choice(value, *, allowed, name):
    text = str(value).strip().lower()
    if text not in allowed:
        allowed_txt = ", ".join(allowed)
        raise ValueError(f"{name} must be one of: {allowed_txt}")
    return text


def _resolve_log_sampling_mask(*, lower, upper, min_orders):
    """
    Decide which dimensions should be sampled in log scale.

    A dimension uses log sampling when:
    - bounds are strictly positive, and
    - log10(upper/lower) >= min_orders.
    """
    lower = np.asarray(lower, dtype=float).ravel()
    upper = np.asarray(upper, dtype=float).ravel()
    threshold = float(min_orders)
    if threshold <= 0.0:
        return np.zeros(lower.size, dtype=bool)

    mask = np.zeros(lower.size, dtype=bool)
    positive = (lower > 0.0) & (upper > 0.0)
    if np.any(positive):
        orders = np.log10(upper[positive] / lower[positive])
        mask[positive] = orders >= threshold
    return mask


def _to_sampling_bounds(*, lower, upper, log_sampling_mask):
    """Convert bounds to sampling space (linear or log10 per dimension)."""
    lower = np.asarray(lower, dtype=float).ravel()
    upper = np.asarray(upper, dtype=float).ravel()
    mask = np.asarray(log_sampling_mask, dtype=bool).ravel()
    if mask.size != lower.size:
        raise ValueError("log_sampling_mask size must match parameter dimension")

    lower_s = lower.copy()
    upper_s = upper.copy()
    if np.any(mask):
        if np.any(lower[mask] <= 0.0) or np.any(upper[mask] <= 0.0):
            raise ValueError("Log-space sampling requires strictly positive bounds")
        lower_s[mask] = np.log10(lower[mask])
        upper_s[mask] = np.log10(upper[mask])
    return lower_s, upper_s


def _from_sampling_space(points, *, log_sampling_mask):
    """Map sampled points back to original parameter space."""
    arr = np.asarray(points, dtype=float).copy()
    mask = np.asarray(log_sampling_mask, dtype=bool).ravel()
    if arr.ndim != 2:
        raise ValueError("points must be 2D")
    if mask.size != arr.shape[1]:
        raise ValueError("log_sampling_mask size must match points dimension")
    if np.any(mask):
        arr[:, mask] = np.power(10.0, arr[:, mask])
    return arr


def _transform_features(points, *, log_sampling_mask):
    """Transform features to interpolation space (linear or log10 by dimension)."""
    arr = np.asarray(points, dtype=float).copy()
    if arr.ndim == 1:
        arr = arr.reshape(1, -1)
    mask = np.asarray(log_sampling_mask, dtype=bool).ravel()
    if mask.size != arr.shape[1]:
        raise ValueError("log_sampling_mask size must match points dimension")
    if np.any(mask):
        if np.any(arr[:, mask] <= 0.0):
            raise ValueError("Cannot apply log transform to non-positive values")
        arr[:, mask] = np.log10(arr[:, mask])
    return arr


def _lhs_in_unit_box(*, n_samples, n_dim, rng):
    """Latin-hypercube samples in [0, 1]^n_dim."""
    n = int(n_samples)
    d = int(n_dim)
    if n <= 0:
        raise ValueError("n_samples must be > 0")
    if d <= 0:
        raise ValueError("n_dim must be > 0")

    unit = np.empty((n, d), dtype=float)
    for j in range(d):
        perm = rng.permutation(n)
        unit[:, j] = (perm + rng.random(n)) / float(n)
    return unit


def _lhs_in_bounds(*, lower, upper, n_samples, rng):
    """Latin-hypercube samples in bounded box [lower, upper]."""
    lower = np.asarray(lower, dtype=float).ravel()
    upper = np.asarray(upper, dtype=float).ravel()
    if lower.size != upper.size:
        raise ValueError("lower and upper must have the same dimension")
    unit = _lhs_in_unit_box(n_samples=n_samples, n_dim=lower.size, rng=rng)
    return lower + unit * (upper - lower)


def _sobol_in_bounds(*, lower, upper, n_samples, seed):
    """Sobol samples in bounded box [lower, upper] (LHS fallback if unavailable)."""
    lower = np.asarray(lower, dtype=float).ravel()
    upper = np.asarray(upper, dtype=float).ravel()
    n = int(n_samples)
    if scipy_qmc is None:
        rng = np.random.default_rng(int(seed))
        return _lhs_in_bounds(lower=lower, upper=upper, n_samples=n, rng=rng)

    sampler = scipy_qmc.Sobol(d=lower.size, scramble=True, seed=int(seed))
    m = int(np.ceil(np.log2(float(n))))
    unit = sampler.random_base2(m=m)[:n]
    return scipy_qmc.scale(unit, lower, upper)


def _regular_in_bounds(*, lower, upper, n_samples):
    """
    Regular deterministic design in [lower, upper].

    - 1D: regular line grid with exactly `n_samples` points.
    - 2D: regular lattice, downsampled uniformly to `n_samples` if needed.
    """
    lower = np.asarray(lower, dtype=float).ravel()
    upper = np.asarray(upper, dtype=float).ravel()
    n = int(n_samples)
    d = lower.size
    if d == 1:
        return np.linspace(lower[0], upper[0], n).reshape(-1, 1)
    if d == 2:
        n_side = int(np.ceil(np.sqrt(float(n))))
        x = np.linspace(lower[0], upper[0], n_side)
        y = np.linspace(lower[1], upper[1], n_side)
        xx, yy = np.meshgrid(x, y)
        points = np.column_stack([xx.ravel(), yy.ravel()])
        if points.shape[0] > n:
            idx = np.linspace(0, points.shape[0] - 1, n, dtype=int)
            points = points[idx]
        return points
    raise ValueError("regular sampling supports only 1D/2D")


def _sample_points(*, lower, upper, n_samples, sampling_strategy, seed, log_sampling_mask):
    """Generate direct-evaluation points with requested sampling strategy."""
    lower = np.asarray(lower, dtype=float).ravel()
    upper = np.asarray(upper, dtype=float).ravel()
    mask = np.asarray(log_sampling_mask, dtype=bool).ravel()
    d = lower.size
    strategy = _normalize_choice(
        sampling_strategy,
        allowed=_SUPPORTED_SAMPLING,
        name="sampling_strategy",
    )
    if strategy == "auto":
        # Auto strategy chosen to avoid aliasing artifacts:
        # - 1D: regular support,
        # - 2D: Sobol space-filling design.
        strategy = "regular" if d == 1 else "sobol"

    lower_s, upper_s = _to_sampling_bounds(lower=lower, upper=upper, log_sampling_mask=mask)

    if strategy == "regular":
        points_s = _regular_in_bounds(lower=lower_s, upper=upper_s, n_samples=n_samples)
    elif strategy == "sobol":
        points_s = _sobol_in_bounds(lower=lower_s, upper=upper_s, n_samples=n_samples, seed=seed)
    else:
        rng = np.random.default_rng(int(seed))
        points_s = _lhs_in_bounds(
            lower=lower_s,
            upper=upper_s,
            n_samples=n_samples,
            rng=rng,
        )
    points = _from_sampling_space(points_s, log_sampling_mask=mask)
    return points, strategy


def _safe_objective_cost(calibration_engine, vector):
    """Evaluate engine cost and coerce failures to +inf."""
    try:
        value = float(calibration_engine.cost(np.asarray(vector, dtype=float)))
    except Exception:
        return float("inf")
    if not np.isfinite(value):
        return float("inf")
    return value


def _interpolate_1d_linear(*, points, values, lower=None, upper=None, grid_size=None, x_grid=None):
    """Linear interpolation on a regular 1D grid."""
    x = np.asarray(points, dtype=float).ravel()
    y = np.asarray(values, dtype=float).ravel()
    order = np.argsort(x)
    x = x[order]
    y = y[order]

    # Merge duplicate x values by averaging costs.
    x_unique, inverse = np.unique(x, return_inverse=True)
    y_sum = np.zeros_like(x_unique, dtype=float)
    y_count = np.zeros_like(x_unique, dtype=float)
    np.add.at(y_sum, inverse, y)
    np.add.at(y_count, inverse, 1.0)
    y_unique = y_sum / np.maximum(y_count, 1.0)

    if x_grid is None:
        if lower is None or upper is None or grid_size is None:
            raise ValueError("lower, upper and grid_size are required when x_grid is not provided")
        n_grid = max(25, int(grid_size))
        x_grid = np.linspace(float(lower), float(upper), n_grid)
    else:
        x_grid = np.asarray(x_grid, dtype=float).ravel()
    y_grid = np.interp(x_grid, x_unique, y_unique)
    return x_grid, y_grid


def _idw_interpolate_2d(
    *,
    points,
    values,
    x_grid,
    y_grid,
    power=2.0,
    eps=1e-12,
    chunk_size=4096,
    log_sampling_mask=(False, False),
):
    """Inverse-distance-weighted interpolation on a 2D grid."""
    pts = _transform_features(points, log_sampling_mask=log_sampling_mask)
    vals = np.asarray(values, dtype=float).ravel()
    xg = np.asarray(x_grid, dtype=float)
    yg = np.asarray(y_grid, dtype=float)

    grid_points = np.column_stack([xg.ravel(), yg.ravel()])
    grid_points = _transform_features(grid_points, log_sampling_mask=log_sampling_mask)
    out = np.empty(grid_points.shape[0], dtype=float)
    p = float(power)
    eps = float(eps)

    for start in range(0, grid_points.shape[0], int(chunk_size)):
        stop = min(start + int(chunk_size), grid_points.shape[0])
        block = grid_points[start:stop]
        dx = block[:, None, 0] - pts[None, :, 0]
        dy = block[:, None, 1] - pts[None, :, 1]
        dist2 = dx * dx + dy * dy

        exact = dist2 <= eps
        if np.any(exact):
            nearest_idx = np.argmax(exact, axis=1)
            exact_rows = np.any(exact, axis=1)
            out_block = np.empty(block.shape[0], dtype=float)
            out_block[exact_rows] = vals[nearest_idx[exact_rows]]
            non_exact_rows = ~exact_rows
            if np.any(non_exact_rows):
                d2 = dist2[non_exact_rows]
                weights = 1.0 / np.power(np.maximum(d2, eps), 0.5 * p)
                out_block[non_exact_rows] = np.sum(weights * vals[None, :], axis=1) / np.sum(
                    weights,
                    axis=1,
                )
            out[start:stop] = out_block
            continue

        weights = 1.0 / np.power(np.maximum(dist2, eps), 0.5 * p)
        out[start:stop] = np.sum(weights * vals[None, :], axis=1) / np.sum(weights, axis=1)

    return out.reshape(xg.shape)


def _gp_predict_mean(
    *,
    x_train,
    y_train,
    x_query,
    lower,
    upper,
    alpha,
    random_seed,
    n_restarts,
    log_sampling_mask,
):
    """
    Fit a Gaussian-process surrogate and predict posterior mean on query points.

    Inputs are scaled to [0, 1]^d to improve numerical conditioning.
    """
    if GaussianProcessRegressor is None or ConstantKernel is None or RBF is None:
        raise RuntimeError("scikit-learn GaussianProcessRegressor is not available")

    x_train = np.asarray(x_train, dtype=float)
    y_train = np.asarray(y_train, dtype=float).ravel()
    x_query = np.asarray(x_query, dtype=float)
    lower = np.asarray(lower, dtype=float).ravel()
    upper = np.asarray(upper, dtype=float).ravel()
    mask = np.asarray(log_sampling_mask, dtype=bool).ravel()

    x_train_t = _transform_features(x_train, log_sampling_mask=mask)
    x_query_t = _transform_features(x_query, log_sampling_mask=mask)
    lower_t, upper_t = _to_sampling_bounds(lower=lower, upper=upper, log_sampling_mask=mask)

    scale = np.maximum(upper_t - lower_t, 1.0e-12)
    x_train_n = (x_train_t - lower_t[None, :]) / scale[None, :]
    x_query_n = (x_query_t - lower_t[None, :]) / scale[None, :]

    n_dim = x_train_n.shape[1]
    kernel = ConstantKernel(1.0, (1.0e-3, 1.0e3)) * RBF(
        length_scale=np.full(n_dim, 0.2, dtype=float),
        length_scale_bounds=(1.0e-2, 1.0e2),
    )
    gp = GaussianProcessRegressor(
        kernel=kernel,
        alpha=max(float(alpha), 1.0e-10),
        normalize_y=True,
        n_restarts_optimizer=max(0, int(n_restarts)),
        random_state=int(random_seed),
    )

    with warnings.catch_warnings():
        if ConvergenceWarning is not None:
            warnings.simplefilter("ignore", category=ConvergenceWarning)
        gp.fit(x_train_n, y_train)
        y_mean = gp.predict(x_query_n, return_std=False)
    return np.asarray(y_mean, dtype=float), gp


def build_objective_surface_approximation(
    calibration_engine,
    *,
    parameter_names,
    bounds,
    n_evaluations,
    random_seed=42,
    grid_size=None,
    sampling_strategy="auto",
    interpolation_strategy="gp",
    gp_alpha=1.0e-8,
    gp_n_restarts=2,
    log_sampling_min_orders=2.0,
):
    """
    Approximate objective surface in 1D/2D from direct model evaluations.

    Default strategy
    ----------------
    - Sampling:
      - 1D: regular support points,
      - 2D: Sobol space-filling design.
    - Interpolation:
      - Gaussian-process surrogate posterior mean (smooth surface).

    Fallbacks
    ---------
    - 1D: linear interpolation if GP is unavailable.
    - 2D: IDW interpolation if GP is unavailable.
    """
    names = tuple(str(name) for name in parameter_names)
    n_dim = len(names)
    if n_dim >= 3:
        return {
            "enabled": False,
            "disabled_reason": "parameter_count_ge_3",
            "n_parameters": int(n_dim),
        }
    if n_dim <= 0:
        return {
            "enabled": False,
            "disabled_reason": "empty_parameter_space",
            "n_parameters": int(n_dim),
        }

    n_eval = int(n_evaluations)
    if n_eval <= 0:
        raise ValueError("n_evaluations must be > 0")

    interpolation_choice = _normalize_choice(
        interpolation_strategy,
        allowed=_SUPPORTED_INTERPOLATION,
        name="interpolation_strategy",
    )
    lower, upper = _ordered_bounds(bounds, names)
    log_sampling_mask = _resolve_log_sampling_mask(
        lower=lower,
        upper=upper,
        min_orders=log_sampling_min_orders,
    )
    sample_points, sampling_used = _sample_points(
        lower=lower,
        upper=upper,
        n_samples=n_eval,
        sampling_strategy=sampling_strategy,
        seed=random_seed,
        log_sampling_mask=log_sampling_mask,
    )
    sample_costs = np.array(
        [_safe_objective_cost(calibration_engine, sample_points[i]) for i in range(sample_points.shape[0])],
        dtype=float,
    )

    finite_mask = np.isfinite(sample_costs)
    finite_points = sample_points[finite_mask]
    finite_costs = sample_costs[finite_mask]
    if finite_points.shape[0] < (2 if n_dim == 1 else 3):
        return {
            "enabled": False,
            "disabled_reason": "not_enough_finite_evaluations",
            "n_parameters": int(n_dim),
            "n_direct_evaluations": int(sample_points.shape[0]),
            "n_finite_evaluations": int(finite_points.shape[0]),
            "parameter_names": names,
        }

    if grid_size is None:
        # Keep rendering cost moderate while giving smooth contours.
        grid_size = int(np.clip(np.sqrt(float(max(n_eval, 1))) * 5.0, 60.0, 180.0))
    grid_size = int(max(25, grid_size))

    gp_used = None
    if n_dim == 1:
        if bool(log_sampling_mask[0]):
            x_grid = np.logspace(np.log10(float(lower[0])), np.log10(float(upper[0])), grid_size)
        else:
            x_grid = np.linspace(float(lower[0]), float(upper[0]), grid_size)
        method_used = None
        cost_grid = None

        use_gp = interpolation_choice in ("auto", "gp")
        if use_gp and finite_points.shape[0] >= 3:
            try:
                gp_pred, gp_used = _gp_predict_mean(
                    x_train=finite_points[:, :1],
                    y_train=finite_costs,
                    x_query=x_grid.reshape(-1, 1),
                    lower=lower[:1],
                    upper=upper[:1],
                    alpha=float(gp_alpha),
                    random_seed=int(random_seed),
                    n_restarts=int(gp_n_restarts),
                    log_sampling_mask=log_sampling_mask[:1],
                )
                cost_grid = gp_pred
                method_used = "gp_1d"
            except Exception:
                method_used = None

        if method_used is None:
            _, cost_grid = _interpolate_1d_linear(
                points=finite_points[:, 0],
                values=finite_costs,
                x_grid=x_grid,
            )
            method_used = "linear_1d"

        return {
            "enabled": True,
            "n_parameters": 1,
            "parameter_names": names,
            "sampling_method": sampling_used,
            "log_sampling_parameter_names": tuple(
                names[i] for i in range(n_dim) if bool(log_sampling_mask[i])
            ),
            "interpolation_method": method_used,
            "n_direct_evaluations": int(sample_points.shape[0]),
            "n_finite_evaluations": int(finite_points.shape[0]),
            "sample_points": finite_points,
            "sample_costs": finite_costs,
            "x_grid": x_grid,
            "cost_grid": np.asarray(cost_grid, dtype=float),
            "surrogate": gp_used,
        }

    x_lin = (
        np.logspace(np.log10(float(lower[0])), np.log10(float(upper[0])), grid_size)
        if bool(log_sampling_mask[0])
        else np.linspace(lower[0], upper[0], grid_size)
    )
    y_lin = (
        np.logspace(np.log10(float(lower[1])), np.log10(float(upper[1])), grid_size)
        if bool(log_sampling_mask[1])
        else np.linspace(lower[1], upper[1], grid_size)
    )
    x_grid, y_grid = np.meshgrid(x_lin, y_lin)
    query_points = np.column_stack([x_grid.ravel(), y_grid.ravel()])

    method_used = None
    z_grid = None
    use_gp = interpolation_choice in ("auto", "gp")
    if use_gp and finite_points.shape[0] >= 6:
        try:
            gp_pred, gp_used = _gp_predict_mean(
                x_train=finite_points[:, :2],
                y_train=finite_costs,
                x_query=query_points,
                lower=lower[:2],
                upper=upper[:2],
                alpha=float(gp_alpha),
                random_seed=int(random_seed),
                n_restarts=int(gp_n_restarts),
                log_sampling_mask=log_sampling_mask[:2],
            )
            z_grid = gp_pred.reshape(x_grid.shape)
            method_used = "gp_2d"
        except Exception:
            method_used = None

    if method_used is None:
        z_grid = _idw_interpolate_2d(
            points=finite_points[:, :2],
            values=finite_costs,
            x_grid=x_grid,
            y_grid=y_grid,
            power=2.0,
            log_sampling_mask=log_sampling_mask[:2],
        )
        method_used = "idw_2d"

    return {
        "enabled": True,
        "n_parameters": 2,
        "parameter_names": names,
        "sampling_method": sampling_used,
        "log_sampling_parameter_names": tuple(
            names[i] for i in range(n_dim) if bool(log_sampling_mask[i])
        ),
        "interpolation_method": method_used,
        "n_direct_evaluations": int(sample_points.shape[0]),
        "n_finite_evaluations": int(finite_points.shape[0]),
        "sample_points": finite_points,
        "sample_costs": finite_costs,
        "x_grid": x_grid,
        "y_grid": y_grid,
        "cost_grid": np.asarray(z_grid, dtype=float),
        "surrogate": gp_used,
    }


__all__ = ("build_objective_surface_approximation",)
