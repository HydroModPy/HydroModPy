"""
Delayed-acceptance Metropolis-Hastings calibration with GP surrogate.

This module implements a two-stage MCMC sampler for expensive simulators:
1) Stage 1 uses a Gaussian-process surrogate of log-posterior to quickly filter
   weak proposals.
2) Stage 2 applies a correction with the true model so the Markov chain targets
   the exact posterior (delayed acceptance).

Posterior convention
--------------------
This implementation assumes that `objective_cost(theta)` returns RMSE.
The log-likelihood used by DA-MH is:
    loglik(theta) = -0.5 * (RMSE(theta) / sigma_noise)^2
and:
    logposterior(theta) = loglik(theta) + logprior(theta)

The implementation follows the calibration-method API:
    calibrator(objective_cost, bounds, **kwargs) -> dict
"""

from __future__ import annotations

import numpy as np

from hydromodpy.calibration.core.results import CalibrationResults

try:
    from scipy.stats import qmc as scipy_qmc
except Exception:  # pragma: no cover - depends on local env
    scipy_qmc = None


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


def _in_bounds(x, lower, upper):
    """
    Check whether a parameter vector lies inside box bounds.
    """
    return bool(np.all((x >= lower) & (x <= upper)))


def _as_vector(value, name, n_dim):
    """
    Convert scalar/vector to 1D vector of expected dimension.
    """
    arr = np.asarray(value, dtype=float).ravel()
    if arr.size == 1:
        return np.full(n_dim, float(arr[0]), dtype=float)
    if arr.size != n_dim:
        raise ValueError(f"{name} must have length {n_dim} (or be scalar)")
    return arr.astype(float)


def sobol_design(bounds, n, seed=42):
    """
    Draw initial design points within bounds using Sobol (or random fallback).
    """
    lower = np.asarray(bounds[:, 0], dtype=float)
    upper = np.asarray(bounds[:, 1], dtype=float)
    n_dim = lower.size
    n = int(n)
    if n <= 0:
        raise ValueError("n must be > 0")

    if scipy_qmc is not None:
        sampler = scipy_qmc.Sobol(d=n_dim, scramble=True, seed=int(seed))
        # `random_base2` avoids Sobol balance warnings for non power-of-two sizes.
        m = int(np.ceil(np.log2(n)))
        x_unit = sampler.random_base2(m=m)[:n]
        return scipy_qmc.scale(x_unit, lower, upper)

    # Fallback keeps the method usable when Sobol is unavailable.
    rng = np.random.default_rng(int(seed))
    return rng.uniform(lower, upper, size=(n, n_dim))


class _SimpleGaussianProcess:
    """
    Lightweight Gaussian-process regressor with anisotropic RBF kernel.

    This internal GP avoids introducing an additional dependency on scikit-learn
    while keeping the delayed-acceptance workflow functional.
    """

    def __init__(self, length_scale, signal_variance=1.0, noise=1e-6):
        self.length_scale = np.asarray(length_scale, dtype=float).ravel()
        self.signal_variance = float(signal_variance)
        self.noise = float(noise)
        self.x_train = None
        self.y_mean = 0.0
        self.y_std = 1.0
        self.l_factor = None
        self.alpha = None

    def _kernel(self, x1, x2):
        x1 = np.asarray(x1, dtype=float)
        x2 = np.asarray(x2, dtype=float)
        diff = (x1[:, None, :] - x2[None, :, :]) / self.length_scale[None, None, :]
        dist2 = np.sum(diff**2, axis=2)
        return self.signal_variance * np.exp(-0.5 * dist2)

    def fit(self, x_train, y_train):
        """
        Fit GP on training pairs `(x_train, y_train)`.
        """
        x = np.asarray(x_train, dtype=float)
        y = np.asarray(y_train, dtype=float).ravel()
        if x.ndim != 2:
            raise ValueError("x_train must be 2D")
        if x.shape[0] != y.size:
            raise ValueError("x_train and y_train sizes are inconsistent")
        if x.shape[0] == 0:
            raise ValueError("empty GP training set")

        self.x_train = x
        self.y_mean = float(np.mean(y))
        y_centered = y - self.y_mean
        y_scale = float(np.std(y_centered))
        self.y_std = y_scale if y_scale > 1e-12 else 1.0
        y_norm = y_centered / self.y_std

        k_xx = self._kernel(x, x)
        diag = np.eye(x.shape[0], dtype=float)
        jitter = max(self.noise, 1e-10)

        for _ in range(8):
            try:
                k_reg = k_xx + (self.noise + jitter) * diag
                l_factor = np.linalg.cholesky(k_reg)
                self.l_factor = l_factor
                break
            except np.linalg.LinAlgError:
                jitter *= 10.0
        else:
            raise np.linalg.LinAlgError("GP kernel matrix is not positive definite")

        tmp = np.linalg.solve(self.l_factor, y_norm)
        self.alpha = np.linalg.solve(self.l_factor.T, tmp)
        return self

    def predict(self, x_pred, return_std=False):
        """
        Predict GP posterior mean (and std if requested) at `x_pred`.
        """
        x = np.asarray(x_pred, dtype=float)
        if x.ndim == 1:
            x = x.reshape(1, -1)
        if self.x_train is None:
            raise RuntimeError("GP must be fitted before prediction")

        k_x_xt = self._kernel(x, self.x_train)  # (n_pred, n_train)
        mu_norm = k_x_xt @ self.alpha
        mu = self.y_mean + self.y_std * mu_norm

        if not return_std:
            return mu

        # Var[f(x)] = k(x,x) - k(x,X) K^-1 k(X,x)
        v = np.linalg.solve(self.l_factor, k_x_xt.T)  # (n_train, n_pred)
        k_xx_diag = np.full(x.shape[0], self.signal_variance, dtype=float)
        var_norm = np.maximum(k_xx_diag - np.sum(v**2, axis=0), 1e-12)
        std = self.y_std * np.sqrt(var_norm)
        return mu, std


def _build_logprior_fn(logprior_fn, prior_mean, prior_std, n_dim):
    """
    Resolve explicit prior into a callable log-prior function.
    """
    if logprior_fn is not None:
        if not callable(logprior_fn):
            raise TypeError("logprior_fn must be callable")

        def _wrapped(theta):
            return float(logprior_fn(np.asarray(theta, dtype=float)))

        return _wrapped

    if prior_mean is None and prior_std is None:
        # Uniform prior in bounded domain.
        return lambda theta: 0.0

    if prior_mean is None or prior_std is None:
        raise ValueError("prior_mean and prior_std must both be provided")

    mu = _as_vector(prior_mean, "prior_mean", n_dim)
    sd = _as_vector(prior_std, "prior_std", n_dim)
    if np.any(sd <= 0.0):
        raise ValueError("prior_std values must be > 0")

    def _normal_logprior(theta):
        z = (np.asarray(theta, dtype=float) - mu) / sd
        return float(-0.5 * np.sum(z**2))

    return _normal_logprior


def delayed_acceptance_gp_mh_calibrate(
    objective_cost,
    bounds,
    *,
    sigma_noise=0.1,
    logprior_fn=None,
    prior_mean=None,
    prior_std=None,
    n_init=80,
    n_samples=20000,
    burn_in=2000,
    thin=1,
    proposal_scale=0.2,
    proposal_cov=None,
    retrain_interval=20,
    gp_length_scale=None,
    gp_noise=1e-6,
    full_mh_prob=0.0,
    seed=42,
    cache_decimals=10,
):
    """
    Delayed-acceptance Metropolis-Hastings with Gaussian-process surrogate.

    Posterior definition
    --------------------
    This sampler assumes:
        objective_cost(theta) = RMSE(theta)
    and builds:
        loglik(theta) = -0.5 * (RMSE(theta) / sigma_noise)^2
        logposterior(theta) = loglik(theta) + logprior(theta)

    Parameters
    ----------
    objective_cost : callable
        RMSE cost function to minimize.
    bounds : sequence[(low, high)]
        Parameter bounds.
    sigma_noise : float
        Scale parameter of the Gaussian RMSE likelihood.
    logprior_fn : callable or None
        Explicit log-prior function taking a parameter vector.
    prior_mean, prior_std : array-like or None
        Independent Normal prior parameters. Ignored if `logprior_fn` is given.
    n_init : int
        Number of initial Sobol-design points for GP training.
    n_samples : int
        Number of MCMC iterations.
    burn_in : int
        Number of initial samples discarded in `posterior_samples`.
    thin : int
        Thinning step for `posterior_samples`.
    proposal_scale : float or array-like
        Random-walk proposal std (absolute units of parameters).
    proposal_cov : array-like or None
        Optional full covariance matrix for proposal. If provided, overrides
        `proposal_scale`.
    retrain_interval : int
        Retrain GP every this number of new expensive evaluations.
    gp_length_scale : float or array-like or None
        RBF length scale(s). Defaults to 0.2 * parameter range per dimension.
    gp_noise : float
        GP nugget/noise level for numerical stability.
    full_mh_prob : float
        Probability of bypassing delayed-acceptance and performing one standard
        Metropolis-Hastings step with the true posterior. This can improve
        chain mixing when the surrogate is locally over-confident.
    seed : int
        RNG seed.
    cache_decimals : int
        Rounding precision for expensive-evaluation cache keys.

    Returns
    -------
    CalibrationResults
        MAP estimate, posterior samples and MCMC diagnostics.
    """
    lower, upper = _normalize_bounds(bounds)
    n_dim = lower.size
    bounds_arr = np.column_stack([lower, upper])

    n_init = int(n_init)
    n_samples = int(n_samples)
    burn_in = int(burn_in)
    thin = int(thin)
    retrain_interval = max(1, int(retrain_interval))
    full_mh_prob = float(full_mh_prob)
    if n_init <= 0:
        raise ValueError("n_init must be > 0")
    if n_samples <= 0:
        raise ValueError("n_samples must be > 0")
    if thin <= 0:
        raise ValueError("thin must be > 0")
    if not (0.0 <= full_mh_prob <= 1.0):
        raise ValueError("full_mh_prob must be in [0, 1]")

    rng = np.random.default_rng(int(seed))

    if gp_length_scale is None:
        gp_length_scale = 0.2 * (upper - lower)
    gp_length_scale = _as_vector(gp_length_scale, "gp_length_scale", n_dim)
    gp_length_scale = np.maximum(gp_length_scale, 1e-12)

    logprior = _build_logprior_fn(
        logprior_fn=logprior_fn,
        prior_mean=prior_mean,
        prior_std=prior_std,
        n_dim=n_dim,
    )
    sigma_noise = float(sigma_noise)
    if sigma_noise <= 0.0:
        raise ValueError("sigma_noise must be > 0")
    inv_sigma2 = 1.0 / (sigma_noise**2)

    def _logposterior(theta):
        theta = np.asarray(theta, dtype=float).ravel()
        if not _in_bounds(theta, lower, upper):
            return -np.inf
        try:
            rmse_value = float(objective_cost(theta))
        except Exception:
            return -np.inf
        if not np.isfinite(rmse_value) or rmse_value < 0.0:
            return -np.inf
        loglik = -0.5 * inv_sigma2 * (rmse_value**2)
        return float(loglik + logprior(theta))

    # Expensive-evaluation cache to avoid repeated full-model calls.
    cache = {}

    def _cache_key(theta):
        return tuple(np.round(np.asarray(theta, dtype=float), int(cache_decimals)))

    def _cached_logposterior(theta):
        key = _cache_key(theta)
        is_new = False
        if key not in cache:
            cache[key] = float(_logposterior(theta))
            is_new = True
        return cache[key], key, is_new

    # Initial design and GP fit.
    x_train = sobol_design(bounds=bounds_arr, n=n_init, seed=seed)
    y_train = np.array([_cached_logposterior(x)[0] for x in x_train], dtype=float)
    finite_mask = np.isfinite(y_train)
    if not np.any(finite_mask):
        raise RuntimeError("No finite initial log-posterior value found inside bounds")
    x_train = x_train[finite_mask]
    y_train = y_train[finite_mask]
    train_keys = {tuple(np.round(row, int(cache_decimals))) for row in x_train}

    gp = _SimpleGaussianProcess(
        length_scale=gp_length_scale,
        signal_variance=1.0,
        noise=float(gp_noise),
    ).fit(x_train, y_train)

    # Start chain from best initial design point.
    idx_best = int(np.argmax(y_train))
    x = np.asarray(x_train[idx_best], dtype=float).copy()
    log_true_x = float(y_train[idx_best])
    mu_x = float(gp.predict(x.reshape(1, -1))[0])

    if proposal_cov is not None:
        proposal_cov = np.asarray(proposal_cov, dtype=float)
        if proposal_cov.shape != (n_dim, n_dim):
            raise ValueError("proposal_cov must be of shape (n_dim, n_dim)")
        use_cov = True
    else:
        proposal_std = _as_vector(proposal_scale, "proposal_scale", n_dim)
        if np.any(proposal_std <= 0.0):
            raise ValueError("proposal_scale must be > 0")
        use_cov = False

    samples = np.empty((n_samples, n_dim), dtype=float)
    logposterior_trace = np.empty(n_samples, dtype=float)
    stage1_accept = 0
    stage2_accept = 0
    full_mh_trials = 0
    full_mh_accept = 0
    new_eval_since_fit = 0

    for i in range(n_samples):
        if use_cov:
            x_prop = x + rng.multivariate_normal(np.zeros(n_dim, dtype=float), proposal_cov)
        else:
            x_prop = x + rng.normal(0.0, proposal_std, size=n_dim)

        if not _in_bounds(x_prop, lower, upper):
            samples[i] = x
            logposterior_trace[i] = log_true_x
            continue

        if rng.random() < full_mh_prob:
            full_mh_trials += 1
            log_true_prop, prop_key, was_new_eval = _cached_logposterior(x_prop)
            if was_new_eval and np.isfinite(log_true_prop) and prop_key not in train_keys:
                x_train = np.vstack([x_train, x_prop.reshape(1, -1)])
                y_train = np.r_[y_train, log_true_prop]
                train_keys.add(prop_key)
                new_eval_since_fit += 1

            log_alpha_true = log_true_prop - log_true_x
            if np.log(rng.random()) < log_alpha_true:
                full_mh_accept += 1
                x = x_prop
                log_true_x = float(log_true_prop)
                mu_x = float(gp.predict(x.reshape(1, -1))[0])

            if new_eval_since_fit >= retrain_interval:
                gp.fit(x_train, y_train)
                mu_x = float(gp.predict(x.reshape(1, -1))[0])
                new_eval_since_fit = 0

            samples[i] = x
            logposterior_trace[i] = log_true_x
            continue

        mu_prop = float(gp.predict(x_prop.reshape(1, -1))[0])
        log_alpha1 = mu_prop - mu_x
        if np.log(rng.random()) < log_alpha1:
            stage1_accept += 1

            log_true_prop, prop_key, was_new_eval = _cached_logposterior(x_prop)
            # Add only newly evaluated points to surrogate training set.
            if was_new_eval and np.isfinite(log_true_prop) and prop_key not in train_keys:
                x_train = np.vstack([x_train, x_prop.reshape(1, -1)])
                y_train = np.r_[y_train, log_true_prop]
                train_keys.add(prop_key)
                new_eval_since_fit += 1

            log_alpha2 = (log_true_prop - log_true_x) - (mu_prop - mu_x)
            if np.log(rng.random()) < log_alpha2:
                stage2_accept += 1
                x = x_prop
                log_true_x = float(log_true_prop)
                mu_x = mu_prop

            # Periodically retrain the surrogate with accumulated expensive calls.
            if new_eval_since_fit >= retrain_interval:
                gp.fit(x_train, y_train)
                mu_x = float(gp.predict(x.reshape(1, -1))[0])
                new_eval_since_fit = 0

        samples[i] = x
        logposterior_trace[i] = log_true_x

    if new_eval_since_fit > 0:
        gp.fit(x_train, y_train)

    burn_in = min(max(burn_in, 0), n_samples)
    posterior_samples = samples[burn_in::thin].copy()

    idx_map = int(np.argmax(logposterior_trace))
    x_map = samples[idx_map].copy()
    logpost_map = float(logposterior_trace[idx_map])
    try:
        cost_best = float(objective_cost(x_map))
    except Exception:
        cost_best = np.inf

    if posterior_samples.size > 0:
        posterior_mean = np.mean(posterior_samples, axis=0)
    else:
        posterior_mean = x_map.copy()

    return CalibrationResults(
        method="da_mh_gp",
        x_best=x_map,
        params_best=None,
        cost_best=cost_best,
        score_best=None,
        n_evaluations=int(len(cache)),
        samples=posterior_samples,
        metadata={
            "chain_samples": samples,
            "logposterior_trace": logposterior_trace,
            "x_map": x_map,
            "logpost_map": logpost_map,
            "posterior_mean": posterior_mean,
            "stage1_accept_rate": float(stage1_accept / n_samples),
            "stage2_accept_rate": float(stage2_accept / n_samples),
            "full_mh_prob": float(full_mh_prob),
            "full_mh_trials": int(full_mh_trials),
            "full_mh_accept_rate": (
                float(full_mh_accept / full_mh_trials) if full_mh_trials > 0 else 0.0
            ),
            "n_init": int(n_init),
            "n_samples": int(n_samples),
            "burn_in": int(burn_in),
            "thin": int(thin),
            "sigma_noise": sigma_noise,
        },
    )

