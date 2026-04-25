"""Gaussian-process surrogate adapter with Expected Improvement acquisition.

Ported from the legacy ``gp_mapping`` calibration method (see
``old/hydromodpy/analysis/calibration/core/methods/gp_mapping.py``).

The adapter works in the transformed parameter space exposed by
:class:`~hydromodpy.calibration.parameters.ParameterSpace`. An initial
Latin-hypercube design is sampled and evaluated; subsequent iterations
fit a :class:`sklearn.gaussian_process.GaussianProcessRegressor`
surrogate to the accumulated (x, y) pairs and pick the next point by
maximising Expected Improvement against the best observed value.

The optimizer declares convergence when EI at its argmax falls below a
configurable threshold (default ``1e-6``).
"""

from __future__ import annotations

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
    from scipy.optimize import minimize as _scipy_minimize
    from scipy.stats import norm as _scipy_norm
    from sklearn.exceptions import ConvergenceWarning
    from sklearn.gaussian_process import GaussianProcessRegressor
    from sklearn.gaussian_process.kernels import RBF, ConstantKernel

    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover - tested via sklearn availability guard
    _SKLEARN_AVAILABLE = False
    ConvergenceWarning = None
    GaussianProcessRegressor = None
    ConstantKernel = None
    RBF = None
    _scipy_minimize = None
    _scipy_norm = None


def _lhs_unit(n: int, d: int, rng: np.random.Generator) -> np.ndarray:
    """Return ``n`` Latin-hypercube samples in the unit hypercube ``[0, 1)^d``."""
    u = np.empty((n, d), dtype=float)
    for j in range(d):
        perm = rng.permutation(n)
        u[:, j] = (perm + rng.random(n)) / float(n)
    return u


def _expected_improvement(
    x: np.ndarray,
    gp: GaussianProcessRegressor,
    y_best: float,
    xi: float = 0.0,
) -> np.ndarray:
    """Return EI at ``x`` for a minimisation problem (negative = objective)."""
    x = np.atleast_2d(np.asarray(x, dtype=float))
    mu, sigma = gp.predict(x, return_std=True)
    sigma = np.asarray(sigma, dtype=float)
    sigma = np.clip(sigma, 1e-12, None)
    improvement = y_best - mu - xi
    z = improvement / sigma
    ei = improvement * _scipy_norm.cdf(z) + sigma * _scipy_norm.pdf(z)
    ei = np.where(sigma > 0.0, ei, 0.0)
    return np.clip(ei, 0.0, None)


@register_optimizer("gp_mapping")
class GPMappingOptimizer:
    """Gaussian-process surrogate optimizer using Expected Improvement.

    Parameters
    ----------
    space
        Parameter space (bounds + transforms).
    max_iter
        Total evaluation budget (initial design included). Defaults to
        ``30``; matches the budget used in the regression test.
    n_init
        Initial Latin-hypercube sample size. Defaults to ``10``. Clamped
        to ``max_iter`` to avoid requesting more points than allowed.
    seed
        RNG seed for both the initial design and the EI restarts.
    ei_tol
        Convergence threshold on Expected Improvement at its argmax.
    ei_patience
        Number of consecutive iterations with EI below ``ei_tol`` required
        before reporting convergence. Defaults to ``3`` to guard against
        spurious "GP confident at sampled points" early-exits.
    xi
        Exploration-exploitation tradeoff constant (default ``0.0``).
    n_restarts
        Number of restarts for the EI maximiser (``scipy.optimize.minimize``).
    n_refine
        Legacy hyperparameter. Number of refinement rounds beyond the
        initial Latin-hypercube design. When provided, the effective budget
        becomes ``max(max_iter, n_init + n_refine * batch_size)`` so callers
        used to the legacy semantics get the requested refinement passes.
    batch_size
        Legacy hyperparameter. Number of EI candidates returned per
        refinement round. Default ``1``. When ``> 1`` the adapter caches
        ``batch_size`` distinct EI maximisers (top-``batch_size`` of the
        random multi-start pool) and serves them sequentially before fitting
        the GP again.
    n_candidates
        Legacy hyperparameter. Number of random multi-starts used when
        maximising EI. Maps to ``n_restarts`` (the larger of the two wins
        so explicit values keep their meaning).
    kappa
        Legacy hyperparameter. UCB-style exploration constant. When
        non-zero the acquisition switches from Expected Improvement to
        Lower Confidence Bound ``mu - kappa * sigma`` (minimisation).
        Default ``0.0`` keeps the EI behaviour.
    alpha
        Legacy hyperparameter. Noise floor of the GP regressor (passed
        directly to :class:`sklearn.gaussian_process.GaussianProcessRegressor`).
        Default ``1e-6`` matches the previous hard-coded value.
    jitter
        Legacy hyperparameter. Additive Cholesky jitter. The effective GP
        nugget is ``alpha + jitter``. Default ``0.0``.
    log_transform
        Legacy hyperparameter. Hint that parameters should be searched in
        log space. The new ``ParameterSpace`` exposes per-parameter
        transforms (``Calibrable(transform="log")``); this flag is accepted
        for back-compat. When ``True`` and **no** parameter declares a
        non-identity transform, a ``RuntimeWarning`` is emitted because the
        adapter cannot retroactively apply log-scaling without re-resolving
        the parameter space. Set transforms on the parameters themselves
        for the actual scaling.
    n_posterior_pool, n_posterior_samples
        Legacy hyperparameters. Sizes used by the legacy ``gp_mapping``
        post-processing step that drew posterior samples from the fitted
        GP for ``model_distribution`` exports. The adapter records these
        on the instance (``self._n_posterior_pool``,
        ``self._n_posterior_samples``) so downstream consumers (the
        calibration distribution writer) can read them, but they do not
        steer the EI search. Accepted as no-op for the optimiser proper.
    """

    name = "gp_mapping"

    def __init__(
        self,
        space: ParameterSpace,
        *,
        max_iter: int = 30,
        n_init: int = 10,
        seed: int | None = None,
        ei_tol: float = 1e-6,
        ei_patience: int = 3,
        xi: float = 0.0,
        n_restarts: int = 5,
        n_refine: int | None = None,
        batch_size: int = 1,
        n_candidates: int | None = None,
        kappa: float = 0.0,
        alpha: float = 1e-6,
        jitter: float = 0.0,
        log_transform: bool = False,
        n_posterior_pool: int = 0,
        n_posterior_samples: int = 0,
    ):
        if not _SKLEARN_AVAILABLE:
            raise ImportError(
                "scikit-learn is required for the 'gp_mapping' optimizer. "
                "Install it via `pip install scikit-learn`."
            )
        self.space = space
        self._batch_size = max(1, int(batch_size))
        n_init_clamped = max(1, int(n_init))
        if n_refine is not None:
            requested_budget = n_init_clamped + max(0, int(n_refine)) * self._batch_size
            self._max_iter = max(int(max_iter), requested_budget)
        else:
            self._max_iter = int(max_iter)
        self._n_init = max(1, min(n_init_clamped, self._max_iter))
        self._seed = seed
        self._ei_tol = float(ei_tol)
        self._ei_patience = max(1, int(ei_patience))
        self._xi = float(xi)
        # ``n_candidates`` is the legacy synonym for ``n_restarts``; honour
        # whichever is larger so explicit user intent is never silently
        # downgraded.
        n_restarts_eff = int(n_restarts)
        if n_candidates is not None:
            n_restarts_eff = max(n_restarts_eff, int(n_candidates))
        self._n_restarts = max(1, n_restarts_eff)
        self._kappa = float(kappa)
        self._alpha = float(alpha)
        self._jitter = float(jitter)
        self._alpha_eff = float(alpha) + max(0.0, float(jitter))
        self._n_posterior_pool = max(0, int(n_posterior_pool))
        self._n_posterior_samples = max(0, int(n_posterior_samples))
        if log_transform and not any(
            getattr(p, "transform", "identity") != "identity" for p in space.parameters
        ):
            warnings.warn(
                "gp_mapping received log_transform=True but no parameter in the "
                "space declares a non-identity transform; set transform='log' on "
                "the relevant CalibParameter entries instead.",
                RuntimeWarning,
                stacklevel=2,
            )
        self._log_transform_hint = bool(log_transform)
        # Cached batch of EI candidates served sequentially when batch_size > 1.
        self._batch_queue: list[np.ndarray] = []

        self._rng = np.random.default_rng(seed)
        self._dim = space.dim
        self._bounds_t = np.array(
            [(p.lower_transformed, p.upper_transformed) for p in space.parameters],
            dtype=float,
        )
        # Pre-sample the initial Latin-hypercube design.
        u = _lhs_unit(self._n_init, self._dim, self._rng)
        lower = self._bounds_t[:, 0]
        upper = self._bounds_t[:, 1]
        self._initial_points: list[np.ndarray] = [
            (lower + u[i] * (upper - lower)) for i in range(self._n_init)
        ]

        self._trial_id = 0
        self._pending: dict[int, np.ndarray] = {}  # trial_id -> transformed x
        self._x_history: list[np.ndarray] = []  # transformed x
        self._y_history: list[float] = []  # objective values
        self._results: list[EvaluationResult] = []
        self._last_ei: float = float("inf")
        self._low_ei_streak: int = 0
        self._exhausted = False
        self._warned_fit_failure = False

    # ------------------------------------------------------------------
    # Protocol: ask / tell / suggest_next / best / converged
    # ------------------------------------------------------------------

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        out: list[ParamSuggestion] = []
        for _ in range(n):
            if self._exhausted:
                break
            if len(self._x_history) + len(self._pending) >= self._max_iter:
                self._exhausted = True
                break
            x_t = self._propose_next()
            if x_t is None:
                self._exhausted = True
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
            raise StopIteration("gp_mapping exhausted")
        return got[0]

    def tell(self, results: Sequence[EvaluationResult]) -> None:
        for r in results:
            x_t = self._pending.pop(r.trial_id, None)
            if x_t is None:
                continue
            self._results.append(r)
            value = r.objective_value
            if r.status != "completed" or not np.isfinite(value):
                value = 1e12
            self._x_history.append(np.asarray(x_t, dtype=float))
            self._y_history.append(float(value))

    def best(self) -> EvaluationResult | None:
        valid = [r for r in self._results if r.status == "completed"]
        if not valid:
            return None
        return min(valid, key=lambda r: r.objective_value)

    def converged(self) -> bool:
        if self._exhausted:
            return True
        if len(self._x_history) < self._n_init:
            return False
        # EI alone is not a robust stopping signal - the GP often reports
        # vanishingly small EI once it becomes confident. Require a run of
        # ``ei_patience`` consecutive iterations below ``ei_tol``.
        return self._low_ei_streak >= self._ei_patience

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _propose_next(self) -> np.ndarray | None:
        """Return the next transformed parameter vector to evaluate."""
        # During the initial design we simply serve the pre-sampled points.
        n_served = len(self._x_history) + len(self._pending)
        if n_served < self._n_init:
            return self._initial_points[n_served]

        # Serve a queued candidate from the previously fitted batch before
        # retraining the GP - this preserves the legacy "batch_size" semantics.
        if self._batch_queue:
            return self._batch_queue.pop(0)

        # Fit the GP on observed (x, y) pairs, then maximise the acquisition.
        x_train = np.asarray(self._x_history, dtype=float)
        y_train = np.asarray(self._y_history, dtype=float)
        gp = self._fit_gp(x_train, y_train)
        if gp is None:
            # Fallback: uniform random draw in the transformed bounds.
            lower = self._bounds_t[:, 0]
            upper = self._bounds_t[:, 1]
            return self._rng.uniform(lower, upper)

        y_best = float(np.min(y_train))
        candidates = self._maximise_acquisition(gp, y_best)
        x_next, ei_next = candidates[0]
        self._last_ei = float(ei_next)
        if self._last_ei < self._ei_tol:
            self._low_ei_streak += 1
        else:
            self._low_ei_streak = 0
        # Stash extra candidates for the next ``ask`` calls when batch_size > 1.
        if self._batch_size > 1:
            self._batch_queue = [c[0] for c in candidates[1 : self._batch_size]]
        return x_next

    def _fit_gp(
        self,
        x_train: np.ndarray,
        y_train: np.ndarray,
    ) -> GaussianProcessRegressor | None:
        # RBF matches the legacy gp_mapping kernel (nu=infinity analogue of
        # Matern), which the Brutsaert golden was generated against.
        kernel = ConstantKernel(1.0, (1e-3, 1e3)) * RBF(
            length_scale=np.ones(self._dim, dtype=float),
            length_scale_bounds=(1e-3, 1e3),
        )
        gp = GaussianProcessRegressor(
            kernel=kernel,
            alpha=self._alpha_eff,
            normalize_y=True,
            random_state=(self._seed if self._seed is not None else 0),
            n_restarts_optimizer=2,
        )
        try:
            with warnings.catch_warnings():
                if ConvergenceWarning is not None:
                    warnings.simplefilter("ignore", category=ConvergenceWarning)
                gp.fit(x_train, y_train)
        except Exception:
            if not self._warned_fit_failure:  # pragma: no cover - defensive
                warnings.warn(
                    "GP surrogate fit failed; falling back to random proposals.",
                    RuntimeWarning,
                    stacklevel=2,
                )
                self._warned_fit_failure = True
            return None
        return gp

    def _acquisition(
        self,
        x: np.ndarray,
        gp: GaussianProcessRegressor,
        y_best: float,
    ) -> np.ndarray:
        """Return the acquisition values at ``x`` (higher = better)."""
        if self._kappa != 0.0:
            # Lower Confidence Bound for minimisation: pick the smallest
            # ``mu - kappa * sigma``. Return its negation so the caller
            # always maximises.
            x = np.atleast_2d(np.asarray(x, dtype=float))
            mu, sigma = gp.predict(x, return_std=True)
            sigma = np.clip(np.asarray(sigma, dtype=float), 0.0, None)
            lcb = mu - float(self._kappa) * sigma
            return -lcb
        return _expected_improvement(x, gp, y_best, xi=self._xi)

    def _maximise_acquisition(
        self,
        gp: GaussianProcessRegressor,
        y_best: float,
    ) -> list[tuple[np.ndarray, float]]:
        """Return up to ``batch_size`` ``(x, score)`` pairs sorted by score (desc)."""
        lower = self._bounds_t[:, 0]
        upper = self._bounds_t[:, 1]
        bounds_scipy = list(zip(lower, upper, strict=True))

        def _neg_score(x: np.ndarray) -> float:
            return -float(self._acquisition(x, gp, y_best)[0])

        starts = self._rng.uniform(lower, upper, size=(self._n_restarts, self._dim))
        candidates: list[tuple[np.ndarray, float]] = []
        for start in starts:
            try:
                res = _scipy_minimize(
                    _neg_score,
                    start,
                    method="L-BFGS-B",
                    bounds=bounds_scipy,
                )
            except Exception:  # pragma: no cover - defensive
                continue
            x_clipped = np.clip(np.asarray(res.x, dtype=float), lower, upper)
            candidates.append((x_clipped, float(-res.fun)))

        if not candidates:
            # Deterministic fallback: rank random starts by acquisition.
            scores = self._acquisition(starts, gp, y_best)
            order = np.argsort(-np.asarray(scores, dtype=float))
            return [(np.clip(starts[i], lower, upper), float(scores[i])) for i in order]

        candidates.sort(key=lambda pair: pair[1], reverse=True)
        # Deduplicate near-identical optima so batch_size > 1 actually serves
        # diverse points; tolerance is a fraction of the bounds span.
        span = np.maximum(upper - lower, 1e-12)
        deduped: list[tuple[np.ndarray, float]] = []
        for x, score in candidates:
            if all(np.linalg.norm((x - d[0]) / span) > 1e-3 for d in deduped):
                deduped.append((x, score))
        return deduped or candidates


__all__ = ["GPMappingOptimizer"]
