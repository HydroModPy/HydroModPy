"""Brutsaert recession analytical calibration case.

This module ports the legacy ``recession_brutsaert`` reference case into the
new calibration architecture. Everything is pure Python:

- :class:`BaseflowConfig` carries the fixed physical context;
- :func:`build_noisy_coarse_sand_chronicle` builds a synthetic noisy chronicle
  from analytical recession equations (exponential or Boussinesq form);
- :func:`make_baseflow_simulator` returns a ``simulator(K, Sy)`` closure;
- :func:`calibrate_brutsaert` wires the simulator to
  :class:`~hydromodpy.calibration.engine.CalibrationEngine` (or calls SciPy
  directly when exact reproduction of the legacy golden is required) and
  returns a compact result dictionary matching the legacy golden schema.

The case calibrates only ``K`` and ``Sy`` against a synthetic discharge time
series; all other parameters of the analytical solution (``Q0``, ``A``,
``L``, ``b``, ``ag``, ``p``) are treated as fixed context.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np

from hydromodpy.calibration import (
    CalibParameter,
    CalibrationEngine,
    EvaluationResult,
    ParameterSpace,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.results.metrics import kge as _kge_metric

# ---------------------------------------------------------------------------
# Fixed physical context
# ---------------------------------------------------------------------------

MODEL_PARAMETER_ORDER = ("K", "Sy")


@dataclass
class BaseflowConfig:
    """Fixed physical settings used by the analytical simulator.

    Only ``K`` and ``Sy`` are calibrated; all other fields are held fixed
    for one calibration run.
    """

    Q0: float
    solution: str = "boussinesq"
    b: float | None = None
    A: float | None = None
    L: float | None = None
    ag: float = 0.7
    p: float = 0.346


# ---------------------------------------------------------------------------
# Analytical equations (port of legacy ``model.py``)
# ---------------------------------------------------------------------------


def _resolve_area_length(A: float | None, L: float | None) -> tuple[float, float]:
    """Resolve ``(A, L)`` pair using ``L = 1.4 * sqrt(A)`` when one is missing."""
    if A is None and L is None:
        raise ValueError("Either A or L must be provided")
    if L is None:
        L = 1.4 * np.sqrt(A)
    if A is None:
        A = (L / 1.4) ** 2
    return float(A), float(L)


def _simulate_baseflow(
    t: np.ndarray,
    Q0: float,
    K: float,
    Sy: float,
    *,
    solution: str = "boussinesq",
    b: float | None = None,
    A: float | None = None,
    L: float | None = None,
    ag: float = 0.7,
    p: float = 0.346,
) -> np.ndarray:
    """Evaluate analytical baseflow discharge ``Q(t)``.

    Supports the ``"exponential"`` and ``"boussinesq"`` solutions of the
    Brutsaert recession equation.
    """
    t = np.asarray(t, dtype=float)
    A_val, L_val = _resolve_area_length(A, L)
    if solution == "exponential":
        if b is None:
            raise ValueError("Aquifer thickness b required for exponential solution")
        return Q0 * np.exp(-(np.pi**2 * K * p * b * L_val**2) / (Sy * (ag * A_val) ** 2) * t)
    if solution == "boussinesq":
        return (
            Q0 ** (-0.5) + (4.8038 / 2.0) * np.sqrt(K) * L_val / (Sy * (ag * A_val) ** 1.5) * t
        ) ** (-2)
    raise ValueError(f"invalid solution: {solution!r}")


def _compute_characteristic_time(
    Q0: float,
    K: float,
    Sy: float,
    *,
    solution: str = "boussinesq",
    b: float | None = None,
    A: float | None = None,
    L: float | None = None,
    ag: float = 0.7,
    p: float = 0.346,
) -> float:
    """Return the characteristic recession time scale ``tc`` [s]."""
    A_val, L_val = _resolve_area_length(A, L)
    if solution == "exponential":
        if b is None:
            raise ValueError("Aquifer thickness b required for exponential solution")
        a = np.pi**2 * K * p * b * L_val**2 / (Sy * (ag * A_val) ** 2)
        return 1.0 / a
    if solution == "boussinesq":
        beta = (4.8038 / 2.0) * np.sqrt(K) * L_val / (Sy * (ag * A_val) ** 1.5)
        return 1.0 / (beta * np.sqrt(Q0))
    raise ValueError(f"invalid solution: {solution!r}")


# ---------------------------------------------------------------------------
# Synthetic chronicle builder
# ---------------------------------------------------------------------------


_DEFAULT_CHRONICLE_PARAMS: dict[str, Any] = {
    "Q0": 0.35,
    "K": 2.0e-4,
    "Sy": 0.28,
    "solution": "boussinesq",
    "A": 1.2e6,
    "L": None,
    "b": None,
    "ag": 0.7,
    "p": 0.346,
    "n_points": 24,
    "log_spacing": True,
    "t_min_days": 0.1,
    "error_fraction": 0.08,
    "random_seed": 123,
}


def _add_proportional_gaussian_error(
    values: np.ndarray,
    *,
    error_fraction: float,
    random_seed: int | None,
) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(values_noisy, sigma)`` with ``sigma = error_fraction * |x|``."""
    if error_fraction < 0.0:
        raise ValueError("error_fraction must be >= 0")
    x = np.asarray(values, dtype=float)
    sigma = error_fraction * np.abs(x)
    rng = np.random.default_rng(random_seed)
    noise = rng.normal(loc=0.0, scale=sigma, size=x.shape)
    return x + noise, sigma


def build_noisy_coarse_sand_chronicle(
    profile_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Generate a synthetic noisy Brutsaert recession chronicle.

    Parameters
    ----------
    profile_params
        Mapping overriding the default coarse-sand configuration. Any key
        present in the defaults may be overridden. Unknown keys are
        ignored to keep the case tolerant to ad-hoc experiments.

    Returns
    -------
    dict
        Payload with keys ``params``, ``t_seconds``, ``t_days``,
        ``q_true``, ``q_observed``, ``sigma``, ``tc_seconds``.
    """
    merged = dict(_DEFAULT_CHRONICLE_PARAMS)
    if profile_params:
        for key, value in profile_params.items():
            if key in merged:
                merged[key] = value

    # Basic sanity checks (mirror legacy pydantic validators).
    for positive in ("Q0", "K", "Sy", "t_min_days"):
        if float(merged[positive]) <= 0.0:
            raise ValueError(f"{positive} must be > 0")
    if merged.get("A") is not None and float(merged["A"]) <= 0.0:
        raise ValueError("A must be > 0")
    if merged.get("L") is not None and float(merged["L"]) <= 0.0:
        raise ValueError("L must be > 0")
    if merged.get("b") is not None and float(merged["b"]) <= 0.0:
        raise ValueError("b must be > 0")
    if not 0.0 <= float(merged["ag"]) <= 1.0:
        raise ValueError("ag must be in [0, 1]")
    if int(merged["n_points"]) <= 0:
        raise ValueError("n_points must be > 0")
    if float(merged["error_fraction"]) < 0.0:
        raise ValueError("error_fraction must be >= 0")

    tc = _compute_characteristic_time(
        Q0=float(merged["Q0"]),
        K=float(merged["K"]),
        Sy=float(merged["Sy"]),
        solution=str(merged["solution"]),
        b=merged.get("b"),
        A=merged.get("A"),
        L=merged.get("L"),
        ag=float(merged["ag"]),
        p=float(merged["p"]),
    )

    t_min_days = float(merged["t_min_days"])
    t_max_days = 5.0 * tc / 86400.0
    n_points = int(merged["n_points"])
    if bool(merged["log_spacing"]):
        if t_min_days <= 0.0:
            raise ValueError("t_min_days must be > 0 when log_spacing is True")
        if t_min_days >= t_max_days:
            raise ValueError("t_min_days must be < t_max_days")
        t_days = np.logspace(np.log10(t_min_days), np.log10(t_max_days), n_points)
    else:
        t_days = np.linspace(0.0, t_max_days, n_points)
    t_seconds = t_days * 86400.0

    q_true = _simulate_baseflow(
        t=t_seconds,
        Q0=float(merged["Q0"]),
        K=float(merged["K"]),
        Sy=float(merged["Sy"]),
        solution=str(merged["solution"]),
        b=merged.get("b"),
        A=merged.get("A"),
        L=merged.get("L"),
        ag=float(merged["ag"]),
        p=float(merged["p"]),
    )

    random_seed = merged.get("random_seed")
    q_observed, sigma = _add_proportional_gaussian_error(
        q_true,
        error_fraction=float(merged["error_fraction"]),
        random_seed=None if random_seed is None else int(random_seed),
    )

    return {
        "params": merged,
        "t_seconds": t_seconds,
        "t_days": t_days,
        "q_true": q_true,
        "q_observed": q_observed,
        "sigma": sigma,
        "tc_seconds": float(tc),
    }


# ---------------------------------------------------------------------------
# Simulator factory
# ---------------------------------------------------------------------------


def make_baseflow_simulator(
    t_seconds: np.ndarray,
    model_config: BaseflowConfig,
) -> Callable[[float, float], np.ndarray]:
    """Return a closure ``simulate(K, Sy) -> Q(t)``.

    The closure reuses the fixed physical context from ``model_config`` and
    is the object consumed by the calibration evaluator.
    """
    t_arr = np.asarray(t_seconds, dtype=float).ravel()
    if t_arr.size == 0:
        raise ValueError("t_seconds cannot be empty")

    def _simulate(K: float, Sy: float) -> np.ndarray:
        return _simulate_baseflow(
            t=t_arr,
            Q0=model_config.Q0,
            K=float(K),
            Sy=float(Sy),
            solution=model_config.solution,
            b=model_config.b,
            A=model_config.A,
            L=model_config.L,
            ag=model_config.ag,
            p=model_config.p,
        )

    return _simulate


# ---------------------------------------------------------------------------
# Metrics (matching legacy compute_performance_metrics)
# ---------------------------------------------------------------------------


def _nse(obs: np.ndarray, sim: np.ndarray) -> float:
    mask = np.isfinite(obs) & np.isfinite(sim)
    o, s = obs[mask], sim[mask]
    denom = float(np.sum((o - o.mean()) ** 2))
    if denom == 0.0:
        return float("nan")
    return 1.0 - float(np.sum((s - o) ** 2)) / denom


def _nse_log(obs: np.ndarray, sim: np.ndarray) -> float:
    mask = np.isfinite(obs) & np.isfinite(sim)
    o, s = obs[mask], sim[mask]
    if np.any(o <= 0.0) or np.any(s <= 0.0):
        return float("nan")
    return _nse(np.log(o), np.log(s))


def _kge_with_components(obs: np.ndarray, sim: np.ndarray) -> dict[str, float]:
    """KGE 2009 with ddof=1 components - matches legacy golden."""
    mask = np.isfinite(obs) & np.isfinite(sim)
    o, s = obs[mask], sim[mask]
    obs_mean = float(np.mean(o))
    sim_mean = float(np.mean(s))
    obs_std = float(np.std(o, ddof=1))
    sim_std = float(np.std(s, ddof=1))
    if obs_std == 0.0 or obs_mean == 0.0:
        return {"KGE": float("nan"), "r": float("nan"), "alpha": float("nan"), "beta": float("nan")}
    r = float(np.corrcoef(o, s)[0, 1])
    alpha = sim_std / obs_std
    beta = sim_mean / obs_mean
    kge = 1.0 - float(np.sqrt((r - 1.0) ** 2 + (alpha - 1.0) ** 2 + (beta - 1.0) ** 2))
    return {"KGE": kge, "r": r, "alpha": alpha, "beta": beta}


def _compute_metrics(obs: np.ndarray, sim: np.ndarray) -> dict[str, float]:
    """Compute the full performance-metric bundle used by the golden."""
    obs = np.asarray(obs, dtype=float).ravel()
    sim = np.asarray(sim, dtype=float).ravel()
    if obs.shape != sim.shape:
        raise ValueError("observed and simulated must have the same shape")
    kge_parts = _kge_with_components(obs, sim)
    return {
        "NSE": float(_nse(obs, sim)),
        "NSElog": float(_nse_log(obs, sim)),
        "KGE": float(kge_parts["KGE"]),
        "r": float(kge_parts["r"]),
        "alpha": float(kge_parts["alpha"]),
        "beta": float(kge_parts["beta"]),
    }


# ---------------------------------------------------------------------------
# Cost functions
# ---------------------------------------------------------------------------


def _kge_cost(obs: np.ndarray, sim: np.ndarray) -> float:
    """``1 - KGE`` (minimization)."""
    value = _kge_metric(sim, obs)["kge"]
    if not np.isfinite(value):
        return 1e12
    return 1.0 - float(value)


def _rmse_cost(obs: np.ndarray, sim: np.ndarray) -> float:
    mask = np.isfinite(obs) & np.isfinite(sim)
    if mask.sum() == 0:
        return 1e12
    return float(np.sqrt(np.mean((sim[mask] - obs[mask]) ** 2)))


_COST_FNS: dict[str, Callable[[np.ndarray, np.ndarray], float]] = {
    "kge": _kge_cost,
    "rmse": _rmse_cost,
}


# ---------------------------------------------------------------------------
# Default configuration used by the regression test
# ---------------------------------------------------------------------------


_DEFAULT_CHRONICLE_TEST: dict[str, Any] = {
    "Q0": 0.35,
    "K": 2.0e-4,
    "Sy": 0.28,
    "solution": "boussinesq",
    "A": 1.2e6,
    "ag": 0.7,
    "p": 0.346,
    "n_points": 24,
    "log_spacing": True,
    "t_min_days": 0.1,
    "error_fraction": 0.08,
    "random_seed": 123,
}

_DEFAULT_BOUNDS: dict[str, tuple[float, float]] = {
    "K": (1.0e-5, 1.0e-3),
    "Sy": (0.20, 0.35),
}

_DEFAULT_METHOD_KWARGS: dict[str, dict[str, Any]] = {
    "grid_search": {"n_per_dim": 5, "log_scale_indices": [0]},
    "random_search": {"n_samples": 80, "seed": 7, "log_scale_indices": [0]},
    "nelder_mead": {"max_iter": 60},
    "simplex": {"max_iter": 60, "max_fun": 120, "xtol": 1e-10, "ftol": 1e-10},
    "cma_es": {"sigma0": 0.2, "max_evaluations": 36, "seed": 7, "normalize": True},
    "gp_mapping": {
        "max_iter": 15,
        "n_init": 8,
        "seed": 7,
        "log_scale_indices": [0],
    },
    "da_mh_gp": {
        "sigma_noise": 0.20,
        "n_init": 12,
        "max_iter": 80,
        "burn_in": 10,
        "proposal_sigma": 0.05,
        "retrain_interval": 10,
        "seed": 123,
        "log_scale_indices": [0],
    },
}


# ---------------------------------------------------------------------------
# Method-specific drivers
# ---------------------------------------------------------------------------


def _run_grid_search(
    *,
    simulator: Callable[[float, float], np.ndarray],
    q_observed: np.ndarray,
    bounds: Mapping[str, tuple[float, float]],
    cost_fn: Callable[[np.ndarray, np.ndarray], float],
    n_per_dim: int | list[int],
    log_scale_indices: list[int] | None,
) -> tuple[np.ndarray, float, int]:
    """Grid search over ``(K, Sy)`` with per-axis log/linear transform.

    Wired through ``CalibrationEngine`` + ``GridAdapter`` with the
    log/linear schedule (log K, linear Sy).
    """
    log_idx = set() if log_scale_indices is None else set(log_scale_indices)
    params: list[CalibParameter] = []
    for i, name in enumerate(MODEL_PARAMETER_ORDER):
        low, high = bounds[name]
        transform = "log" if i in log_idx else "identity"
        params.append(
            CalibParameter(name=name, lower=float(low), upper=float(high), transform=transform)
        )
    space = ParameterSpace(params)

    if isinstance(n_per_dim, int):
        points_per_dim = [int(n_per_dim)] * space.dim
    else:
        if len(n_per_dim) != space.dim:
            raise ValueError("n_per_dim length must match parameter dimension")
        points_per_dim = [int(v) for v in n_per_dim]

    engine = CalibrationEngine(
        space=space,
        optimizer=build_optimizer("grid", space, points_per_dim=points_per_dim),
        evaluator=_make_engine_evaluator(simulator, q_observed, cost_fn),
        max_iter=int(np.prod(points_per_dim)),
        batch_size=1,
    )
    session = engine.run()
    best = session.best
    if best is None:
        raise RuntimeError("grid search produced no result")
    history = [r for r in session.history if r.status == "completed"]
    best_values = _lookup_values(session, best.trial_id)
    x_best = np.array([best_values[name] for name in MODEL_PARAMETER_ORDER], dtype=float)
    return x_best, float(best.objective_value), len(history)


def _run_random_search(
    *,
    simulator: Callable[[float, float], np.ndarray],
    q_observed: np.ndarray,
    bounds: Mapping[str, tuple[float, float]],
    cost_fn: Callable[[np.ndarray, np.ndarray], float],
    n_samples: int,
    seed: int,
    log_scale_indices: list[int] | None,
) -> tuple[np.ndarray, float, int]:
    """Random search with numpy ``default_rng``.

    Uses the explicit numpy RNG stream so the golden output is stable
    under a 1e-10 tolerance (Optuna's random sampler would diverge).
    """
    log_idx = set() if log_scale_indices is None else set(log_scale_indices)
    lower = np.array([bounds[name][0] for name in MODEL_PARAMETER_ORDER], dtype=float)
    upper = np.array([bounds[name][1] for name in MODEL_PARAMETER_ORDER], dtype=float)

    rng = np.random.default_rng(int(seed))
    n_samples = int(n_samples)
    if n_samples <= 0:
        raise ValueError("n_samples must be >= 1")

    samples = np.empty((n_samples, lower.size), dtype=float)
    for i in range(lower.size):
        if i in log_idx:
            log_vals = rng.uniform(np.log10(lower[i]), np.log10(upper[i]), n_samples)
            samples[:, i] = np.power(10.0, log_vals)
        else:
            samples[:, i] = rng.uniform(lower[i], upper[i], n_samples)

    best_cost = np.inf
    best_x = samples[0].copy()
    for x in samples:
        sim = simulator(float(x[0]), float(x[1]))
        cost = float(cost_fn(q_observed, sim))
        if cost < best_cost:
            best_cost = cost
            best_x = x.copy()
    return best_x, float(best_cost), n_samples


def _run_scipy_minimize(
    *,
    simulator: Callable[[float, float], np.ndarray],
    q_observed: np.ndarray,
    bounds: Mapping[str, tuple[float, float]],
    cost_fn: Callable[[np.ndarray, np.ndarray], float],
    method_name: str,
    max_iter: int,
    max_fun: int | None = None,
    xtol: float = 1e-10,
    ftol: float = 1e-10,
) -> tuple[np.ndarray, float, int]:
    """Local optimisation via Nelder-Mead or simplex with penalised bounds.

    Uses a penalised cost wrapper so the optimiser stays within bounds
    without relying on a SciPy bounded implementation that could diverge
    across versions.
    """
    from scipy import optimize as scipy_optimize

    lower = np.array([bounds[name][0] for name in MODEL_PARAMETER_ORDER], dtype=float)
    upper = np.array([bounds[name][1] for name in MODEL_PARAMETER_ORDER], dtype=float)

    def _clip(x: np.ndarray) -> np.ndarray:
        return np.minimum(np.maximum(x, lower), upper)

    penalty_weight = 1e4

    def _cost(x: np.ndarray) -> float:
        x = np.asarray(x, dtype=float)
        under = np.maximum(lower - x, 0.0)
        over = np.maximum(x - upper, 0.0)
        penalty = 0.0
        if np.any(under > 0.0) or np.any(over > 0.0):
            penalty = float(penalty_weight) * float(np.sum(under**2 + over**2))
        x_in = _clip(x)
        sim = simulator(float(x_in[0]), float(x_in[1]))
        return float(cost_fn(q_observed, sim) + penalty)

    x0 = 0.5 * (lower + upper)

    if method_name == "nelder_mead":
        result = scipy_optimize.minimize(
            _cost,
            x0,
            method="Nelder-Mead",
            options={"maxiter": int(max_iter), "xatol": float(xtol), "fatol": float(ftol)},
        )
        x_best = _clip(np.asarray(result.x, dtype=float))
        sim_best = simulator(float(x_best[0]), float(x_best[1]))
        cost_best = float(cost_fn(q_observed, sim_best))
        return x_best, cost_best, int(result.nfev)

    if method_name == "simplex":
        fmin_kwargs: dict[str, Any] = {
            "func": _cost,
            "x0": x0,
            "xtol": float(xtol),
            "ftol": float(ftol),
            "maxiter": int(max_iter),
            "full_output": True,
            "disp": False,
            "retall": False,
        }
        if max_fun is not None:
            fmin_kwargs["maxfun"] = int(max_fun)
        x_raw, _f_opt, _n_iter, n_func, _warnflag = scipy_optimize.fmin(**fmin_kwargs)
        x_best = _clip(np.asarray(x_raw, dtype=float))
        sim_best = simulator(float(x_best[0]), float(x_best[1]))
        cost_best = float(cost_fn(q_observed, sim_best))
        return x_best, cost_best, int(n_func)

    raise ValueError(f"Unsupported scipy method: {method_name!r}")


def _run_cma_es(
    *,
    simulator: Callable[[float, float], np.ndarray],
    q_observed: np.ndarray,
    bounds: Mapping[str, tuple[float, float]],
    cost_fn: Callable[[np.ndarray, np.ndarray], float],
    sigma0: float,
    max_evaluations: int,
    seed: int,
    normalize: bool,
) -> tuple[np.ndarray, float, int]:
    """CMA-ES through Optuna's ``CmaEsSampler``.

    Optuna's sampler is used; tolerances on the ``8e-3`` level account for
    convergence behaviour differing from the older ``cma`` package.
    """
    # Optuna's CmaEsSampler handles bound scaling internally, so we pass
    # bounds directly without a pre-normalisation step.
    _ = normalize  # reserved for explicit per-axis scaling overrides
    lower = np.array([bounds[name][0] for name in MODEL_PARAMETER_ORDER], dtype=float)
    upper = np.array([bounds[name][1] for name in MODEL_PARAMETER_ORDER], dtype=float)
    space = ParameterSpace(
        [
            CalibParameter(name=name, lower=float(lower[i]), upper=float(upper[i]))
            for i, name in enumerate(MODEL_PARAMETER_ORDER)
        ]
    )

    optimizer = build_optimizer("optuna", space, sampler="cmaes", seed=int(seed))
    # Force the sampler to start from the midpoint with the requested
    # sigma0 by updating the CmaEs-specific attributes if available.
    _configure_cmaes(optimizer, sigma0=float(sigma0))

    max_eval = int(max_evaluations)
    engine = CalibrationEngine(
        space=space,
        optimizer=optimizer,
        evaluator=_make_engine_evaluator(simulator, q_observed, cost_fn),
        max_iter=max_eval,
        batch_size=1,
    )
    session = engine.run()
    best = session.best
    if best is None:
        raise RuntimeError("cma_es produced no result")
    history = [r for r in session.history if r.status == "completed"]
    best_values = _lookup_values(session, best.trial_id)
    x_best = np.array([best_values[name] for name in MODEL_PARAMETER_ORDER], dtype=float)
    return x_best, float(best.objective_value), len(history)


def _run_gp_mapping(
    *,
    simulator: Callable[[float, float], np.ndarray],
    q_observed: np.ndarray,
    bounds: Mapping[str, tuple[float, float]],
    cost_fn: Callable[[np.ndarray, np.ndarray], float],
    max_iter: int,
    n_init: int,
    seed: int,
    log_scale_indices: list[int] | None,
) -> tuple[np.ndarray, float, int]:
    """Gaussian-process surrogate + Expected-Improvement driver.

    Wired through ``CalibrationEngine`` + ``GPMappingOptimizer``. The
    caller picks which dimensions live on a log axis via
    ``log_scale_indices`` (the legacy default used log K, linear Sy).
    """
    log_idx = set() if log_scale_indices is None else set(log_scale_indices)
    params: list[CalibParameter] = []
    for i, name in enumerate(MODEL_PARAMETER_ORDER):
        low, high = bounds[name]
        transform = "log" if i in log_idx else "identity"
        params.append(
            CalibParameter(name=name, lower=float(low), upper=float(high), transform=transform)
        )
    space = ParameterSpace(params)

    optimizer = build_optimizer(
        "gp_mapping",
        space,
        max_iter=int(max_iter),
        n_init=int(n_init),
        seed=int(seed),
    )
    engine = CalibrationEngine(
        space=space,
        optimizer=optimizer,
        evaluator=_make_engine_evaluator(simulator, q_observed, cost_fn),
        max_iter=int(max_iter),
        batch_size=1,
    )
    session = engine.run()
    best = session.best
    if best is None:
        raise RuntimeError("gp_mapping produced no result")
    history = [r for r in session.history if r.status == "completed"]
    best_values = _lookup_values(session, best.trial_id)
    x_best = np.array([best_values[name] for name in MODEL_PARAMETER_ORDER], dtype=float)
    return x_best, float(best.objective_value), len(history)


def _run_da_mh_gp(
    *,
    simulator: Callable[[float, float], np.ndarray],
    q_observed: np.ndarray,
    bounds: Mapping[str, tuple[float, float]],
    cost_fn: Callable[[np.ndarray, np.ndarray], float],
    sigma_noise: float,
    n_init: int,
    max_iter: int,
    burn_in: int,
    proposal_sigma: float,
    retrain_interval: int,
    seed: int,
    log_scale_indices: list[int] | None,
) -> tuple[np.ndarray, float, int]:
    """Delayed-Acceptance MH with GP surrogate.

    Wired through ``CalibrationEngine`` + ``DaMhGpOptimizer``. The optimizer
    expects the evaluator to return RMSE (the log-likelihood is built
    internally from ``sigma_noise``). ``log_scale_indices`` selects the log
    axis for K (matches the legacy default).

    The engine's ``max_iter`` is sized as ``n_init + max_iter`` so the
    optimizer can first consume its Sobol initial design and then run the
    chain budget without getting capped by the engine.
    """
    log_idx = set() if log_scale_indices is None else set(log_scale_indices)
    params: list[CalibParameter] = []
    for i, name in enumerate(MODEL_PARAMETER_ORDER):
        low, high = bounds[name]
        transform = "log" if i in log_idx else "identity"
        params.append(
            CalibParameter(name=name, lower=float(low), upper=float(high), transform=transform)
        )
    space = ParameterSpace(params)

    optimizer = build_optimizer(
        "da_mh_gp",
        space,
        sigma_noise=float(sigma_noise),
        n_init=int(n_init),
        max_iter=int(max_iter),
        burn_in=int(burn_in),
        proposal_sigma=float(proposal_sigma),
        retrain_interval=int(retrain_interval),
        seed=int(seed),
    )
    # Engine budget must cover init design + accepted proposals; the
    # optimizer's background thread stops on its own.
    engine_budget = int(n_init) + int(max_iter) + 16
    engine = CalibrationEngine(
        space=space,
        optimizer=optimizer,
        evaluator=_make_engine_evaluator(simulator, q_observed, cost_fn),
        max_iter=engine_budget,
        batch_size=1,
    )
    session = engine.run()
    best = session.best
    if best is None:
        raise RuntimeError("da_mh_gp produced no result")

    history = [r for r in session.history if r.status == "completed"]
    # ``best`` is the posterior mode if available; fall back to the trial's
    # values when the optimizer could not populate the chain.
    mode = None
    if best.metadata:
        mode = best.metadata.get("posterior_mode")
    if mode is not None:
        x_best = np.array([float(mode[name]) for name in MODEL_PARAMETER_ORDER], dtype=float)
    else:
        best_values = _lookup_values(session, best.trial_id)
        x_best = np.array([best_values[name] for name in MODEL_PARAMETER_ORDER], dtype=float)

    sim_best = simulator(float(x_best[0]), float(x_best[1]))
    cost_best = float(cost_fn(q_observed, sim_best))
    return x_best, cost_best, len(history)


def _configure_cmaes(optimizer: Any, *, sigma0: float) -> None:
    """Best-effort tuning of Optuna's CMA-ES sampler.

    Optuna's ``CmaEsSampler`` accepts ``sigma0`` as constructor argument
    but our adapter only forwards ``seed`` - we patch it after the fact
    so the calibration matches the legacy sigma0 choice when possible.
    """
    try:
        study = optimizer._study
        sampler = getattr(study, "sampler", None)
        if sampler is not None and hasattr(sampler, "_sigma0"):
            sampler._sigma0 = float(sigma0)
    except Exception:  # pragma: no cover - cosmetic tuning
        return


# ---------------------------------------------------------------------------
# Engine plumbing helpers
# ---------------------------------------------------------------------------


def _make_engine_evaluator(
    simulator: Callable[[float, float], np.ndarray],
    q_observed: np.ndarray,
    cost_fn: Callable[[np.ndarray, np.ndarray], float],
) -> Callable[[ParamSuggestion], EvaluationResult]:
    """Return an evaluator closure that runs the simulator and computes cost."""
    # The evaluator also caches the suggested ``values`` mapping keyed by
    # trial_id so we can recover physical parameters from ``best()`` later.
    trial_values: dict[int, Mapping[str, float]] = {}

    def _evaluator(sugg: ParamSuggestion) -> EvaluationResult:
        trial_values[sugg.trial_id] = dict(sugg.values)
        try:
            sim = simulator(float(sugg.values["K"]), float(sugg.values["Sy"]))
            cost = float(cost_fn(q_observed, sim))
            status = "completed"
        except Exception:
            cost = 1e12
            status = "crashed"
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=cost,
            status=status,
            metadata={"values": dict(sugg.values)},
        )

    # Attach a lookup table so downstream code can recover parameter values.
    _evaluator.trial_values = trial_values  # type: ignore[attr-defined]
    return _evaluator


def _lookup_values(session: Any, trial_id: int) -> Mapping[str, float]:
    """Recover the physical ``{name: value}`` mapping for a completed trial."""
    for r in session.history:
        if r.trial_id != trial_id:
            continue
        metadata = r.metadata or {}
        if "values" in metadata:
            return metadata["values"]
    raise KeyError(f"trial_id {trial_id} not found in session history")


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def calibrate_brutsaert(
    method: str,
    *,
    chronicle: Mapping[str, Any] | None = None,
    bounds: Mapping[str, tuple[float, float]] | None = None,
    objective_metric: str = "kge",
    method_kwargs: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run a Brutsaert recession calibration and return a compact result.

    Parameters
    ----------
    method
        Legacy method name; one of ``"grid_search"``, ``"random_search"``,
        ``"nelder_mead"``, ``"simplex"``, ``"cma_es"``.
    chronicle
        Optional override of the default noisy-chronicle parameters.
    bounds
        Optional ``{"K": (low, high), "Sy": (low, high)}`` override.
    objective_metric
        Either ``"kge"`` (default) or ``"rmse"``.
    method_kwargs
        Per-method override dictionary merged on top of the legacy defaults.

    Returns
    -------
    dict
        Keys: ``method``, ``x_best``, ``cost_best``, ``score_best``,
        ``n_evaluations``, ``metrics``. Matches the legacy golden schema.
    """
    method_name = str(method)
    metric_key = objective_metric.lower()
    if metric_key not in _COST_FNS:
        raise ValueError(f"Unsupported objective_metric: {objective_metric!r}")
    cost_fn = _COST_FNS[metric_key]

    chronicle_params = dict(_DEFAULT_CHRONICLE_TEST)
    if chronicle:
        chronicle_params.update(chronicle)
    chronicle_data = build_noisy_coarse_sand_chronicle(chronicle_params)
    q_observed = chronicle_data["q_observed"]
    t_seconds = chronicle_data["t_seconds"]
    params = chronicle_data["params"]

    model_config = BaseflowConfig(
        Q0=float(params["Q0"]),
        solution=str(params["solution"]),
        b=params.get("b"),
        A=params.get("A"),
        L=params.get("L"),
        ag=float(params.get("ag", 0.7)),
        p=float(params.get("p", 0.346)),
    )
    simulator = make_baseflow_simulator(t_seconds=t_seconds, model_config=model_config)

    effective_bounds: dict[str, tuple[float, float]] = {
        name: (float(low), float(high)) for name, (low, high) in _DEFAULT_BOUNDS.items()
    }
    if bounds:
        for name, pair in bounds.items():
            effective_bounds[name] = (float(pair[0]), float(pair[1]))

    kwargs: dict[str, Any] = dict(_DEFAULT_METHOD_KWARGS.get(method_name, {}))
    if method_kwargs:
        kwargs.update(method_kwargs)

    if method_name == "grid_search":
        x_best, cost_best, n_eval = _run_grid_search(
            simulator=simulator,
            q_observed=q_observed,
            bounds=effective_bounds,
            cost_fn=cost_fn,
            n_per_dim=kwargs.get("n_per_dim", 5),
            log_scale_indices=kwargs.get("log_scale_indices"),
        )
    elif method_name == "random_search":
        x_best, cost_best, n_eval = _run_random_search(
            simulator=simulator,
            q_observed=q_observed,
            bounds=effective_bounds,
            cost_fn=cost_fn,
            n_samples=int(kwargs.get("n_samples", 80)),
            seed=int(kwargs.get("seed", 7)),
            log_scale_indices=kwargs.get("log_scale_indices"),
        )
    elif method_name in ("nelder_mead", "simplex"):
        x_best, cost_best, n_eval = _run_scipy_minimize(
            simulator=simulator,
            q_observed=q_observed,
            bounds=effective_bounds,
            cost_fn=cost_fn,
            method_name=method_name,
            max_iter=int(kwargs.get("max_iter", 60)),
            max_fun=kwargs.get("max_fun"),
            xtol=float(kwargs.get("xtol", 1e-10)),
            ftol=float(kwargs.get("ftol", 1e-10)),
        )
    elif method_name == "cma_es":
        x_best, cost_best, n_eval = _run_cma_es(
            simulator=simulator,
            q_observed=q_observed,
            bounds=effective_bounds,
            cost_fn=cost_fn,
            sigma0=float(kwargs.get("sigma0", 0.2)),
            max_evaluations=int(kwargs.get("max_evaluations", 36)),
            seed=int(kwargs.get("seed", 7)),
            normalize=bool(kwargs.get("normalize", True)),
        )
    elif method_name == "gp_mapping":
        x_best, cost_best, n_eval = _run_gp_mapping(
            simulator=simulator,
            q_observed=q_observed,
            bounds=effective_bounds,
            cost_fn=cost_fn,
            max_iter=int(kwargs.get("max_iter", 15)),
            n_init=int(kwargs.get("n_init", 8)),
            seed=int(kwargs.get("seed", 7)),
            log_scale_indices=kwargs.get("log_scale_indices"),
        )
    elif method_name == "da_mh_gp":
        # DA-MH-GP assumes the evaluator returns RMSE (the sampler builds a
        # Gaussian log-likelihood from it), so force the metric accordingly.
        if metric_key != "rmse":
            cost_fn = _COST_FNS["rmse"]
            metric_key = "rmse"
        x_best, cost_best, n_eval = _run_da_mh_gp(
            simulator=simulator,
            q_observed=q_observed,
            bounds=effective_bounds,
            cost_fn=cost_fn,
            sigma_noise=float(kwargs.get("sigma_noise", 0.20)),
            n_init=int(kwargs.get("n_init", 12)),
            max_iter=int(kwargs.get("max_iter", 80)),
            burn_in=int(kwargs.get("burn_in", 10)),
            proposal_sigma=float(kwargs.get("proposal_sigma", 0.05)),
            retrain_interval=int(kwargs.get("retrain_interval", 10)),
            seed=int(kwargs.get("seed", 123)),
            log_scale_indices=kwargs.get("log_scale_indices"),
        )
    else:
        raise ValueError(f"Unsupported calibration method: {method_name!r}")

    sim_best = simulator(float(x_best[0]), float(x_best[1]))
    metrics = _compute_metrics(q_observed, sim_best)

    # ``score_best`` semantics (legacy):
    # - KGE minimization: score = KGE value at x_best (higher better)
    # - RMSE minimization: score = cost itself (legacy quirk)
    if metric_key == "kge":
        score_best = float(metrics["KGE"])
    else:
        score_best = float(cost_best)

    return {
        "method": method_name,
        "x_best": x_best.tolist(),
        "cost_best": float(cost_best),
        "score_best": float(score_best),
        "n_evaluations": int(n_eval),
        "metrics": metrics,
    }


__all__ = [
    "MODEL_PARAMETER_ORDER",
    "BaseflowConfig",
    "build_noisy_coarse_sand_chronicle",
    "calibrate_brutsaert",
    "make_baseflow_simulator",
]
