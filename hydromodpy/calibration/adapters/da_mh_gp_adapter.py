"""Delayed-Acceptance Metropolis-Hastings with Gaussian-process surrogate.

Ported from the legacy ``da_mh_gp`` calibration method (see
``old/hydromodpy/analysis/calibration/core/methods/da_mh_gp.py``).

Two-stage MCMC for expensive simulators: stage 1 filters proposals with a
sklearn GaussianProcessRegressor surrogate of the log-posterior; stage 2
corrects the acceptance ratio with one full-model call, so the chain targets
the exact posterior. The surrogate is retrained every ``retrain_interval``
new evaluations. The objective is assumed to return **RMSE**; the
log-likelihood is built internally as ``-0.5 * (RMSE / sigma_noise)**2``.
The sampler pulls evaluations from the engine via a background thread
(like ``scipy_adapter``).
"""

from __future__ import annotations

import queue
import threading
import warnings
from collections.abc import Sequence

import numpy as np

from hydromodpy.calibration.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    register_optimizer,
)
from hydromodpy.calibration.parameters import ParameterSpace

try:
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel, WhiteKernel

    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover - tested via sklearn availability guard
    _SKLEARN_AVAILABLE = False
    ConvergenceWarning = None
    GaussianProcessRegressor = None
    ConstantKernel = None
    RBF = None
    WhiteKernel = None

_SENTINEL = object()


def _sobol_or_uniform(n: int, lower: np.ndarray, upper: np.ndarray, seed: int) -> np.ndarray:
    """Return an initial design. Uses Sobol when SciPy is available, else uniform."""
    d = lower.size
    try:
        from scipy.stats import qmc

        sampler = qmc.Sobol(d=d, scramble=True, seed=int(seed))
        m = int(np.ceil(np.log2(max(2, n))))
        x_unit = sampler.random_base2(m=m)[:n]
        return qmc.scale(x_unit, lower, upper)
    except Exception:  # pragma: no cover - Sobol fallback
        rng = np.random.default_rng(int(seed))
        return rng.uniform(lower, upper, size=(n, d))


def _as_vector(value: object, name: str, n_dim: int) -> np.ndarray:
    """Scalar → full vector; vector → float cast. Used for proposal sigma etc."""
    arr = np.asarray(value, dtype=float).ravel()
    if arr.size == 1:
        return np.full(n_dim, float(arr[0]), dtype=float)
    if arr.size != n_dim:
        raise ValueError(f"{name} must have length {n_dim} (or be scalar)")
    return arr.astype(float)


class _EngineBridge:
    """Bridge between a pull-style MCMC and the ask/tell engine via two queues."""

    def __init__(self) -> None:
        self._pending_in: queue.Queue[float | object] = queue.Queue()
        self._pending_out: queue.Queue[np.ndarray | None] = queue.Queue()
        self._done = threading.Event()

    def submit(self, x_t: np.ndarray) -> float:
        self._pending_out.put(np.asarray(x_t, dtype=float).copy())
        value = self._pending_in.get()
        if value is _SENTINEL:
            raise RuntimeError("sampler aborted by engine")
        return float(value)

    def terminate(self) -> None:
        self._done.set()
        self._pending_out.put(None)

    def next_point(self, timeout: float | None = None) -> np.ndarray | None:
        return self._pending_out.get(timeout=timeout)

    def feed(self, value: float) -> None:
        self._pending_in.put(float(value))

    def finished(self) -> bool:
        return self._done.is_set()


@register_optimizer("da_mh_gp")
class DaMhGpOptimizer:
    """Delayed-Acceptance Metropolis-Hastings with GP surrogate.

    The evaluator must return **RMSE**; the log-likelihood is built internally
    as ``-0.5 * (RMSE / sigma_noise)**2``. Parameters: ``max_iter`` (chain
    length, default 200), ``burn_in``, ``proposal_sigma`` (random-walk std in
    the transformed space, scalar or per-dimension), ``n_init`` (Sobol design
    size), ``retrain_interval``, ``sigma_noise`` (> 0), ``full_mh_prob`` (in
    [0, 1]), optional ``prior_mean`` / ``prior_std`` Normal prior (otherwise
    uniform on the bounded box), ``seed``.
    """

    name = "da_mh_gp"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        max_iter: int = 200,
        burn_in: int = 20,
        proposal_sigma: float | Sequence[float] = 0.1,
        n_init: int = 20,
        retrain_interval: int = 10,
        sigma_noise: float = 0.2,
        full_mh_prob: float = 0.0,
        prior_mean: float | Sequence[float] | None = None,
        prior_std: float | Sequence[float] | None = None,
        seed: int | None = None,
        # Legacy alias accepted for parity with the TOML schema:
        n_samples: int | None = None,
        proposal_scale: float | Sequence[float] | None = None,
    ):
        if not _SKLEARN_AVAILABLE:
            raise ImportError(
                "scikit-learn is required for the 'da_mh_gp' optimizer. "
                "Install it via `pip install scikit-learn`."
            )
        self.space = space
        self._dim = space.dim
        # Legacy aliases take precedence when provided (TOML parity).
        if n_samples is not None:
            max_iter = int(n_samples)
        if proposal_scale is not None:
            proposal_sigma = proposal_scale

        self._max_iter = int(max_iter)
        self._burn_in = int(max(0, burn_in))
        self._n_init = max(2, int(n_init))
        self._retrain_interval = max(1, int(retrain_interval))
        self._sigma_noise = float(sigma_noise)
        if self._sigma_noise <= 0.0:
            raise ValueError("sigma_noise must be > 0")
        self._full_mh_prob = float(full_mh_prob)
        if not (0.0 <= self._full_mh_prob <= 1.0):
            raise ValueError("full_mh_prob must be in [0, 1]")
        self._seed = 0 if seed is None else int(seed)

        self._bounds_t = np.array(
            [(p.lower_transformed, p.upper_transformed) for p in space.parameters],
            dtype=float,
        )
        self._lower = self._bounds_t[:, 0]
        self._upper = self._bounds_t[:, 1]
        self._proposal_std = _as_vector(proposal_sigma, "proposal_sigma", self._dim)
        if np.any(self._proposal_std <= 0.0):
            raise ValueError("proposal_sigma must be > 0")

        self._prior_mean = (
            None if prior_mean is None else _as_vector(prior_mean, "prior_mean", self._dim)
        )
        self._prior_std = (
            None if prior_std is None else _as_vector(prior_std, "prior_std", self._dim)
        )
        if (self._prior_mean is None) ^ (self._prior_std is None):
            raise ValueError("prior_mean and prior_std must both be set or both None")

        # State.
        self._rng = np.random.default_rng(self._seed)
        self._trial_id = 0
        self._pending: dict[int, np.ndarray] = {}
        self._results: list[EvaluationResult] = []
        self._chain: list[np.ndarray] = []
        self._chain_logpost: list[float] = []
        self._x_train: list[np.ndarray] = []
        self._y_train: list[float] = []

        # Bridge + worker thread that runs the MCMC chain.
        self._bridge = _EngineBridge()
        self._worker = threading.Thread(target=self._run_chain, daemon=True)
        self._worker.start()

    # ------------------------------------------------------------------
    # Log-posterior helpers
    # ------------------------------------------------------------------

    def _in_bounds(self, x: np.ndarray) -> bool:
        return bool(np.all((x >= self._lower) & (x <= self._upper)))

    def _log_prior(self, x: np.ndarray) -> float:
        if self._prior_mean is None:
            return 0.0
        z = (x - self._prior_mean) / self._prior_std
        return float(-0.5 * np.sum(z**2))

    def _rmse_to_logpost(self, x: np.ndarray, rmse: float) -> float:
        if not np.isfinite(rmse) or rmse < 0.0:
            return -np.inf
        loglik = -0.5 * (rmse / self._sigma_noise) ** 2
        return float(loglik + self._log_prior(x))

    def _evaluate_true(self, x_t: np.ndarray) -> float:
        """Fetch the true RMSE from the engine and convert it to a log-posterior."""
        if not self._in_bounds(x_t):
            return -np.inf
        rmse = self._bridge.submit(x_t)
        logpost = self._rmse_to_logpost(x_t, rmse)
        if np.isfinite(logpost):
            self._x_train.append(np.asarray(x_t, dtype=float).copy())
            self._y_train.append(logpost)
        return logpost

    # ------------------------------------------------------------------
    # GP surrogate
    # ------------------------------------------------------------------

    def _fit_gp(self) -> GaussianProcessRegressor | None:
        if len(self._x_train) < 2:
            return None
        x = np.asarray(self._x_train, dtype=float)
        y = np.asarray(self._y_train, dtype=float)
        scale = np.maximum(self._upper - self._lower, 1e-12)
        kernel = ConstantKernel(1.0, (1e-3, 1e3)) * RBF(
            length_scale=0.2 * scale, length_scale_bounds=(1e-6, 1e6)
        ) + WhiteKernel(noise_level=1e-6, noise_level_bounds=(1e-10, 1e-2))
        gp = GaussianProcessRegressor(
            kernel=kernel,
            alpha=1e-8,
            normalize_y=True,
            random_state=self._seed,
            n_restarts_optimizer=0,
        )
        try:
            with warnings.catch_warnings():
                if ConvergenceWarning is not None:
                    warnings.simplefilter("ignore", category=ConvergenceWarning)
                warnings.simplefilter("ignore", category=UserWarning)
                gp.fit(x, y)
        except Exception:  # pragma: no cover - defensive
            return None
        return gp

    def _gp_mean(self, gp: GaussianProcessRegressor | None, x_t: np.ndarray) -> float:
        if gp is None:
            return 0.0
        return float(gp.predict(np.atleast_2d(x_t))[0])

    # ------------------------------------------------------------------
    # MCMC worker
    # ------------------------------------------------------------------

    def _run_chain(self) -> None:
        try:
            self._mcmc_loop()
        finally:
            self._bridge.terminate()

    def _mcmc_loop(self) -> None:
        x_design = _sobol_or_uniform(self._n_init, self._lower, self._upper, self._seed)
        design_logposts = [self._evaluate_true(np.asarray(x, dtype=float)) for x in x_design]
        if not any(np.isfinite(lp) for lp in design_logposts):
            return

        idx_best = int(np.argmax(design_logposts))
        x_cur = np.asarray(x_design[idx_best], dtype=float).copy()
        log_true_cur = float(design_logposts[idx_best])
        gp = self._fit_gp()
        mu_cur = self._gp_mean(gp, x_cur)
        new_evals = 0

        for _ in range(self._max_iter):
            # Record current state before the step so the chain length equals max_iter.
            self._chain.append(x_cur.copy())
            self._chain_logpost.append(log_true_cur)

            x_prop = x_cur + self._rng.normal(0.0, self._proposal_std, size=self._dim)
            if not self._in_bounds(x_prop):
                continue

            bypass = self._rng.random() < self._full_mh_prob
            if not bypass:
                # Stage 1: surrogate filter.
                mu_prop = self._gp_mean(gp, x_prop)
                if np.log(self._rng.random()) >= (mu_prop - mu_cur):
                    continue

            # Stage 2 (or plain MH when bypassing): full-model correction.
            log_true_prop = self._evaluate_true(x_prop)
            if np.isfinite(log_true_prop):
                new_evals += 1
            if bypass:
                log_alpha = log_true_prop - log_true_cur
            else:
                log_alpha = (log_true_prop - log_true_cur) - (mu_prop - mu_cur)
            if np.log(self._rng.random()) < log_alpha:
                x_cur = x_prop
                log_true_cur = log_true_prop
                mu_cur = self._gp_mean(gp, x_cur) if bypass else mu_prop

            if new_evals >= self._retrain_interval:
                gp = self._fit_gp()
                mu_cur = self._gp_mean(gp, x_cur)
                new_evals = 0

    # ------------------------------------------------------------------
    # Protocol: ask / tell / suggest_next / best / converged
    # ------------------------------------------------------------------

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            x_t = self._bridge.next_point()
            if x_t is None:
                break
            self._trial_id += 1
            self._pending[self._trial_id] = x_t
            values = {
                p.name: p.to_physical(float(x_t[i])) for i, p in enumerate(self.space.parameters)
            }
            out.append(ParamSuggestion(trial_id=self._trial_id, values=values, source="ask"))
        return out

    def suggest_next(self) -> ParamSuggestion:
        got = self.ask(1)
        if not got:
            raise StopIteration("da_mh_gp exhausted")
        return got[0]

    def tell(self, results: Sequence[EvaluationResult]) -> None:
        for r in results:
            if r.trial_id not in self._pending:
                continue
            self._pending.pop(r.trial_id, None)
            self._results.append(r)
            value = r.objective_value
            if r.status != "completed" or not np.isfinite(value):
                value = 1e12
            self._bridge.feed(float(value))

    def best(self) -> EvaluationResult | None:
        """Return the posterior mode as an EvaluationResult.

        The mode is the chain sample with the highest log-posterior. We find
        the evaluation closest to that mode in transformed space and enrich
        its metadata with ``posterior_mode`` (physical-space values).
        """
        valid = [r for r in self._results if r.status == "completed"]
        if not valid:
            return None
        if not self._chain_logpost:
            return min(valid, key=lambda r: r.objective_value)

        logposts = np.asarray(self._chain_logpost, dtype=float)
        idx_mode = int(np.argmax(logposts))
        x_mode_t = np.asarray(self._chain[idx_mode], dtype=float)

        def _dist(result: EvaluationResult) -> float:
            values = (result.metadata or {}).get("values")
            if not values:
                return np.inf
            try:
                x_r = np.array(
                    [p.to_transformed(float(values[p.name])) for p in self.space.parameters],
                    dtype=float,
                )
            except Exception:  # pragma: no cover - defensive
                return np.inf
            return float(np.linalg.norm(x_r - x_mode_t))

        picked = min(valid, key=_dist)
        mode_physical = {
            p.name: p.to_physical(float(x_mode_t[i])) for i, p in enumerate(self.space.parameters)
        }
        meta = dict(picked.metadata or {})
        meta["posterior_mode"] = mode_physical
        meta["posterior_mode_logpost"] = float(logposts[idx_mode])
        return EvaluationResult(
            trial_id=picked.trial_id,
            sim_id=picked.sim_id,
            objective_value=picked.objective_value,
            status=picked.status,
            duration_s=picked.duration_s,
            components=picked.components,
            from_cache=picked.from_cache,
            metadata=meta,
        )

    def converged(self) -> bool:
        return self._bridge.finished() and not self._pending

    # ------------------------------------------------------------------
    # Diagnostics (used by downstream workflows/tests)
    # ------------------------------------------------------------------

    @property
    def chain(self) -> np.ndarray:
        """Full chain in transformed space (including burn-in), shape ``(n, d)``."""
        if not self._chain:
            return np.empty((0, self._dim), dtype=float)
        return np.asarray(self._chain, dtype=float)

    @property
    def posterior_samples(self) -> np.ndarray:
        """Chain in **physical** space with burn-in removed, shape ``(n-b, d)``."""
        arr = self.chain
        if arr.size == 0:
            return arr
        burn = min(self._burn_in, arr.shape[0])
        sliced = arr[burn:]
        out = np.empty_like(sliced)
        for i, p in enumerate(self.space.parameters):
            out[:, i] = np.array([p.to_physical(float(v)) for v in sliced[:, i]])
        return out


__all__ = ["DaMhGpOptimizer"]
