"""
Gaussian-process surrogate posterior mapping calibration method.
"""

from __future__ import annotations

import os
import platform
import warnings

import numpy as np

from hydromodpy.analysis.calibration.core.results import CalibrationResults

try:
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import ConstantKernel, RBF
except Exception:  # pragma: no cover - depends on local env
    ConvergenceWarning = None
    GaussianProcessRegressor = None
    ConstantKernel = None
    RBF = None


def _disable_sklearn_gp_optimizer() -> bool:
    """Return whether to bypass sklearn's native GP hyperparameter optimizer."""
    flag = os.environ.get("HYDROMODPY_DISABLE_SKLEARN_GP_OPTIMIZER")
    if flag is not None:
        text = str(flag).strip().lower()
        return text not in ("", "0", "false", "no", "off")
    return platform.system() == "Windows"


def _normalize_bounds(bounds):
    """
    Normalize bounds to float arrays `(lower, upper)` for any dimension.
    """
    bounds_list = [(float(lo), float(hi)) for lo, hi in bounds]
    lower = np.array([b[0] for b in bounds_list], dtype=float)
    upper = np.array([b[1] for b in bounds_list], dtype=float)
    if np.any(lower >= upper):
        raise ValueError("Each bound must satisfy lower < upper")
    return lower, upper


def _sample_lhs(bounds, n_samples, rng):
    """
    Draw a Latin-hypercube design in bounded space.
    """
    lower = bounds[:, 0]
    upper = bounds[:, 1]
    n_dim = lower.size
    n = int(n_samples)
    if n <= 0:
        raise ValueError("n_samples must be > 0")

    unit = np.empty((n, n_dim), dtype=float)
    for j in range(n_dim):
        perm = rng.permutation(n)
        unit[:, j] = (perm + rng.random(n)) / float(n)
    return lower + unit * (upper - lower)


def _sample_uniform(bounds, n_samples, rng):
    """
    Draw i.i.d. uniform points in bounded space.
    """
    lower = bounds[:, 0]
    upper = bounds[:, 1]
    return rng.uniform(lower, upper, size=(int(n_samples), lower.size))


def _gp_predict_mean_std(gp, x, predict_batch_size=50000):
    """
    Predict GP mean/std by batches for memory safety on large candidate pools.
    """
    x = np.asarray(x, dtype=float)
    n = x.shape[0]
    batch = max(1, int(predict_batch_size))
    mu = np.empty(n, dtype=float)
    sigma = np.empty(n, dtype=float)
    for start in range(0, n, batch):
        stop = min(start + batch, n)
        mu_chunk, sigma_chunk = gp.predict(x[start:stop], return_std=True)
        mu[start:stop] = mu_chunk
        sigma[start:stop] = sigma_chunk
    return mu, sigma


def _gp_predict_mean(gp, x, predict_batch_size=50000):
    """
    Predict GP mean by batches for memory safety on large candidate pools.
    """
    x = np.asarray(x, dtype=float)
    n = x.shape[0]
    batch = max(1, int(predict_batch_size))
    mu = np.empty(n, dtype=float)
    for start in range(0, n, batch):
        stop = min(start + batch, n)
        mu[start:stop] = gp.predict(x[start:stop], return_std=False)
    return mu


def _fit_gp_surrogate(gp, x_train, y_train):
    """Fit the GP while silencing boundary convergence warnings."""
    with warnings.catch_warnings():
        if ConvergenceWarning is not None:
            warnings.simplefilter("ignore", category=ConvergenceWarning)
        gp.fit(x_train, y_train)


class _IdwSurrogate:
    """Deterministic surrogate used when sklearn GP is unstable on Windows."""

    def __init__(self, *, power=2.0, eps=1.0e-12, distance_weight=0.25) -> None:
        self.power = float(power)
        self.eps = float(eps)
        self.distance_weight = float(distance_weight)
        self.x_train = None
        self.y_train = None

    def fit(self, x_train, y_train):
        self.x_train = np.asarray(x_train, dtype=float)
        self.y_train = np.asarray(y_train, dtype=float).ravel()
        return self

    def predict(self, x, return_std=False):
        if self.x_train is None or self.y_train is None:
            raise RuntimeError("Surrogate must be fitted before prediction")

        x_query = np.asarray(x, dtype=float)
        if x_query.ndim == 1:
            x_query = x_query.reshape(1, -1)

        dx = x_query[:, None, :] - self.x_train[None, :, :]
        dist2 = np.sum(dx * dx, axis=2)
        exact = dist2 <= self.eps

        mean = np.empty(x_query.shape[0], dtype=float)
        std = np.empty(x_query.shape[0], dtype=float)

        if np.any(exact):
            exact_rows = np.any(exact, axis=1)
            nearest_idx = np.argmax(exact, axis=1)
            mean[exact_rows] = self.y_train[nearest_idx[exact_rows]]
            std[exact_rows] = 0.0
            remaining = ~exact_rows
        else:
            remaining = np.ones(x_query.shape[0], dtype=bool)

        if np.any(remaining):
            d2 = dist2[remaining]
            weights = 1.0 / np.power(np.maximum(d2, self.eps), 0.5 * self.power)
            weight_sum = np.sum(weights, axis=1)
            weighted_mean = np.sum(weights * self.y_train[None, :], axis=1) / np.maximum(
                weight_sum,
                self.eps,
            )
            mean[remaining] = weighted_mean

            centered = self.y_train[None, :] - weighted_mean[:, None]
            weighted_var = np.sum(weights * centered * centered, axis=1) / np.maximum(
                weight_sum,
                self.eps,
            )
            nearest_dist = np.sqrt(np.min(d2, axis=1))
            std[remaining] = np.sqrt(np.maximum(weighted_var, 0.0)) + (
                self.distance_weight * nearest_dist
            )

        if return_std:
            return mean, std
        return mean


def _build_surrogate(*, n_dim, alpha, jitter, seed):
    """Build one calibration surrogate, preferring sklearn GP when stable."""
    if not _disable_sklearn_gp_optimizer():
        kernel = ConstantKernel(1.0, (1e-3, 1e3)) * RBF(
            length_scale=np.ones(n_dim, dtype=float),
            length_scale_bounds=(1e-3, 1e3),
        )
        return GaussianProcessRegressor(
            kernel=kernel,
            alpha=float(alpha) + float(jitter),
            normalize_y=True,
            random_state=int(seed),
            optimizer="fmin_l_bfgs_b",
            n_restarts_optimizer=2,
        )
    return _IdwSurrogate()


def gp_mapping_calibrate(
    objective_cost,
    bounds,
    seed=42,
    n_init=120,
    n_refine=3,
    batch_size=25,
    n_candidates=4000,
    kappa=3.0,
    alpha=1e-6,
    jitter=1e-8,
    n_posterior_pool=200000,
    n_posterior_samples=20000,
    log_transform=True,
):
    """
    GP surrogate posterior mapping with UCB refinement and importance resampling.

    The surrogate models:
        f(theta) = - objective_cost(theta)

    Returns
    -------
    CalibrationResults
        Best point and approximate posterior samples.
    """
    if GaussianProcessRegressor is None or ConstantKernel is None or RBF is None:
        raise ImportError("scikit-learn is required for gp_mapping_calibrate")

    lower, upper = _normalize_bounds(bounds)
    if np.any(lower <= 0.0) or np.any(upper <= 0.0):
        raise ValueError("gp_mapping requires strictly positive parameter bounds")

    n_dim = lower.size
    rng = np.random.default_rng(int(seed))

    n_init = int(n_init)
    n_refine = int(n_refine)
    batch_size = int(batch_size)
    n_candidates = int(n_candidates)
    n_posterior_pool = int(n_posterior_pool)
    n_posterior_samples = int(n_posterior_samples)
    if n_init <= 0:
        raise ValueError("n_init must be > 0")
    if n_refine < 0:
        raise ValueError("n_refine must be >= 0")
    if batch_size <= 0:
        raise ValueError("batch_size must be > 0")
    if n_candidates <= 0:
        raise ValueError("n_candidates must be > 0")
    if n_posterior_pool <= 0:
        raise ValueError("n_posterior_pool must be > 0")
    if n_posterior_samples <= 0:
        raise ValueError("n_posterior_samples must be > 0")

    # Work in transformed space for surrogate fitting when requested.
    if bool(log_transform):
        t_lower = np.log(lower)
        t_upper = np.log(upper)

        def _to_original(x_transformed):
            return np.exp(np.asarray(x_transformed, dtype=float))

    else:
        t_lower = lower.copy()
        t_upper = upper.copy()

        def _to_original(x_transformed):
            return np.asarray(x_transformed, dtype=float)

    t_bounds = np.column_stack([t_lower, t_upper])

    eval_count = 0
    penalty_cost = 1e12

    def _evaluate_cost(theta):
        nonlocal eval_count
        eval_count += 1
        try:
            cost = float(objective_cost(np.asarray(theta, dtype=float)))
        except Exception:
            cost = penalty_cost
        if not np.isfinite(cost):
            cost = penalty_cost
        return cost

    # Step 2: initial design.
    x_train_t = _sample_lhs(t_bounds, n_init, rng=rng)
    x_train = _to_original(x_train_t)
    cost_train = np.array([_evaluate_cost(theta) for theta in x_train], dtype=float)
    y_train = -cost_train

    # Step 3: initial GP fit.
    gp = _build_surrogate(
        n_dim=n_dim,
        alpha=alpha,
        jitter=jitter,
        seed=seed,
    )
    _fit_gp_surrogate(gp, x_train_t, y_train)

    # Step 4: adaptive refinement with UCB.
    for _ in range(n_refine):
        x_cand_t = _sample_uniform(t_bounds, n_candidates, rng=rng)
        mu, sigma = _gp_predict_mean_std(gp, x_cand_t)
        ucb = mu + float(kappa) * sigma

        n_pick = min(batch_size, n_candidates)
        idx_pick = np.argpartition(ucb, -n_pick)[-n_pick:]
        x_new_t = x_cand_t[idx_pick]
        x_new = _to_original(x_new_t)
        cost_new = np.array([_evaluate_cost(theta) for theta in x_new], dtype=float)
        y_new = -cost_new

        x_train_t = np.vstack([x_train_t, x_new_t])
        x_train = np.vstack([x_train, x_new])
        cost_train = np.concatenate([cost_train, cost_new])
        y_train = np.concatenate([y_train, y_new])
        _fit_gp_surrogate(gp, x_train_t, y_train)

    # Best observed point (true evaluations, not surrogate prediction).
    idx_best = int(np.argmin(cost_train))
    x_best = np.asarray(x_train[idx_best], dtype=float)
    cost_best = float(cost_train[idx_best])

    # Step 5: approximate posterior via importance sampling on surrogate mean.
    x_pool_t = _sample_uniform(t_bounds, n_posterior_pool, rng=rng)
    mu_pool = _gp_predict_mean(gp, x_pool_t)
    log_w = mu_pool - float(np.max(mu_pool))
    w = np.exp(log_w)
    w_sum = float(np.sum(w))
    if not np.isfinite(w_sum) or w_sum <= 0.0:
        weights = np.full(n_posterior_pool, 1.0 / float(n_posterior_pool), dtype=float)
    else:
        weights = w / w_sum

    idx_resampled = rng.choice(
        np.arange(n_posterior_pool, dtype=int),
        size=n_posterior_samples,
        replace=True,
        p=weights,
    )
    posterior_samples_t = x_pool_t[idx_resampled]
    posterior_samples = _to_original(posterior_samples_t)

    return CalibrationResults(
        method="gp_mapping",
        x_best=x_best,
        params_best=None,
        cost_best=cost_best,
        score_best=None,
        n_evaluations=int(eval_count),
        samples=posterior_samples,
        metadata={
            "X_train": x_train,
            "y_train": y_train,
            "surrogate": gp,
        },
    )
