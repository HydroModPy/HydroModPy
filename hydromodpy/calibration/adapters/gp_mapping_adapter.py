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
    from sklearn.gaussian_process.kernels import ConstantKernel, Matern

    _SKLEARN_AVAILABLE = True
except ImportError:  # pragma: no cover - tested via sklearn availability guard
    _SKLEARN_AVAILABLE = False
    ConvergenceWarning = None
    GaussianProcessRegressor = None
    ConstantKernel = None
    Matern = None
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
    xi
        Exploration-exploitation tradeoff constant (default ``0.0``).
    n_restarts
        Number of restarts for the EI maximiser (``scipy.optimize.minimize``).
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
        xi: float = 0.0,
        n_restarts: int = 5,
    ):
        if not _SKLEARN_AVAILABLE:
            raise ImportError(
                "scikit-learn is required for the 'gp_mapping' optimizer. "
                "Install it via `pip install scikit-learn`."
            )
        self.space = space
        self._max_iter = int(max_iter)
        self._n_init = max(1, min(int(n_init), self._max_iter))
        self._seed = seed
        self._ei_tol = float(ei_tol)
        self._xi = float(xi)
        self._n_restarts = max(1, int(n_restarts))

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
        return self._last_ei < self._ei_tol

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _propose_next(self) -> np.ndarray | None:
        """Return the next transformed parameter vector to evaluate."""
        # During the initial design we simply serve the pre-sampled points.
        n_served = len(self._x_history) + len(self._pending)
        if n_served < self._n_init:
            return self._initial_points[n_served]

        # Fit the GP on observed (x, y) pairs, then maximise EI.
        x_train = np.asarray(self._x_history, dtype=float)
        y_train = np.asarray(self._y_history, dtype=float)
        gp = self._fit_gp(x_train, y_train)
        if gp is None:
            # Fallback: uniform random draw in the transformed bounds.
            lower = self._bounds_t[:, 0]
            upper = self._bounds_t[:, 1]
            return self._rng.uniform(lower, upper)

        y_best = float(np.min(y_train))
        x_next, ei_next = self._maximise_ei(gp, y_best)
        self._last_ei = float(ei_next)
        return x_next

    def _fit_gp(
        self,
        x_train: np.ndarray,
        y_train: np.ndarray,
    ) -> GaussianProcessRegressor | None:
        kernel = ConstantKernel(1.0, (1e-3, 1e3)) * Matern(
            length_scale=np.ones(self._dim, dtype=float),
            length_scale_bounds=(1e-3, 1e3),
            nu=2.5,
        )
        gp = GaussianProcessRegressor(
            kernel=kernel,
            alpha=1e-6,
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

    def _maximise_ei(
        self,
        gp: GaussianProcessRegressor,
        y_best: float,
    ) -> tuple[np.ndarray, float]:
        """Return ``(x_star, ei_star)`` maximising Expected Improvement."""
        lower = self._bounds_t[:, 0]
        upper = self._bounds_t[:, 1]
        bounds_scipy = list(zip(lower, upper, strict=True))

        def _neg_ei(x: np.ndarray) -> float:
            return -float(_expected_improvement(x, gp, y_best, xi=self._xi)[0])

        best_x = None
        best_neg = np.inf
        starts = self._rng.uniform(lower, upper, size=(self._n_restarts, self._dim))
        for start in starts:
            try:
                res = _scipy_minimize(
                    _neg_ei,
                    start,
                    method="L-BFGS-B",
                    bounds=bounds_scipy,
                )
            except Exception:  # pragma: no cover - defensive
                continue
            if res.fun < best_neg:
                best_neg = float(res.fun)
                best_x = np.asarray(res.x, dtype=float)

        if best_x is None:
            # Deterministic fallback: pick the best random start.
            ei_vals = _expected_improvement(starts, gp, y_best, xi=self._xi)
            idx = int(np.argmax(ei_vals))
            return np.clip(starts[idx], lower, upper), float(ei_vals[idx])

        best_x = np.clip(best_x, lower, upper)
        return best_x, float(-best_neg)


__all__ = ["GPMappingOptimizer"]
