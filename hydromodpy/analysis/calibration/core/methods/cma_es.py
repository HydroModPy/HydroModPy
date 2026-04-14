"""Covariance Matrix Adaptation Evolution Strategy calibration method."""

from __future__ import annotations

import math

import numpy as np

from hydromodpy.analysis.calibration.core.results import CalibrationResults


def _normalize_bounds(bounds):
    """Normalize bounds to float arrays `(lower, upper)`."""
    bounds_list = [(float(lo), float(hi)) for lo, hi in bounds]
    lower = np.array([item[0] for item in bounds_list], dtype=float)
    upper = np.array([item[1] for item in bounds_list], dtype=float)
    if np.any(lower >= upper):
        raise ValueError("Each bound must satisfy lower < upper")
    return lower, upper


def _default_sigma0(*, normalize: bool, lower: np.ndarray, upper: np.ndarray) -> float:
    """Return a conservative default initial CMA-ES scale."""
    if normalize:
        return 0.25
    mean_span = float(np.mean(upper - lower))
    return max(1.0e-12, 0.25 * mean_span)


def _midpoint(*, lower: np.ndarray, upper: np.ndarray, normalize: bool) -> np.ndarray:
    """Return the default start point."""
    if normalize:
        return np.full(lower.shape, 0.5, dtype=float)
    return 0.5 * (lower + upper)


def _clip_unit(values: np.ndarray) -> np.ndarray:
    """Clip normalized values to the closed unit hypercube."""
    return np.clip(np.asarray(values, dtype=float), 0.0, 1.0)


def _to_physical(
    values: np.ndarray,
    *,
    lower: np.ndarray,
    upper: np.ndarray,
    normalize: bool,
) -> np.ndarray:
    """Convert candidate values to the physical bounded parameter space."""
    arr = np.asarray(values, dtype=float)
    if normalize:
        arr = _clip_unit(arr)
        return lower + arr * (upper - lower)
    return np.clip(arr, lower, upper)


def cma_es_calibrate(
    objective_cost,
    bounds,
    x0=None,
    sigma0=None,
    popsize=None,
    max_iter=None,
    max_evaluations=None,
    seed=42,
    restarts=0,
    tolx=None,
    tolfun=None,
    normalize=True,
    verbose=False,
):
    """
    CMA-ES global derivative-free calibration.

    Parameters
    ----------
    objective_cost : callable
        Cost function to minimize.
    bounds : sequence[tuple[float, float]]
        Box bounds in physical parameter space.
    x0 : sequence[float] | None
        Optional initial point in physical parameter space.
    sigma0 : float | None
        Initial search scale. When `normalize=True`, it is interpreted in the
        normalized unit hypercube.
    popsize : int | None
        Optional CMA-ES population size.
    max_iter : int | None
        Optional maximum number of CMA-ES iterations.
    max_evaluations : int | None
        Optional maximum number of objective evaluations.
    seed : int
        Random seed forwarded to `cma`.
    restarts : int
        Number of restart attempts.
    tolx : float | None
        Optional step-size termination tolerance.
    tolfun : float | None
        Optional objective improvement termination tolerance.
    normalize : bool
        When True, optimize in the unit hypercube and map back to physical
        bounds before every expensive evaluation.
    verbose : bool
        Forward compact display to `cma`.
    """
    lower, upper = _normalize_bounds(bounds)
    if x0 is None:
        initial = _midpoint(lower=lower, upper=upper, normalize=bool(normalize))
    else:
        x0_array = np.asarray(x0, dtype=float).reshape(-1)
        if x0_array.size != lower.size:
            raise ValueError(
                f"x0 must have dimension {lower.size}, got {x0_array.size}"
            )
        if bool(normalize):
            span = upper - lower
            initial = np.divide(
                x0_array - lower,
                span,
                out=np.full_like(x0_array, 0.5, dtype=float),
                where=span > 0.0,
            )
            initial = _clip_unit(initial)
        else:
            initial = np.clip(x0_array, lower, upper)
    sigma0_value = float(
        _default_sigma0(normalize=bool(normalize), lower=lower, upper=upper)
        if sigma0 is None
        else sigma0
    )
    if sigma0_value <= 0.0:
        raise ValueError("sigma0 must be > 0")

    try:
        import cma
    except Exception as exc:
        raise ImportError(
            "The 'cma' package is required for cma_es calibration. "
            "Install it with `pip install cma`."
        ) from exc

    n_evaluations = 0

    def _wrapped(candidate):
        nonlocal n_evaluations
        physical = _to_physical(
            np.asarray(candidate, dtype=float),
            lower=lower,
            upper=upper,
            normalize=bool(normalize),
        )
        raw_cost = float(objective_cost(physical))
        n_evaluations += 1
        if math.isfinite(raw_cost):
            return raw_cost
        return 1.0e12

    if restarts is not None and int(restarts) < 0:
        raise ValueError("restarts must be >= 0")
    if tolx is not None:
        if float(tolx) <= 0.0:
            raise ValueError("tolx must be > 0")
    if tolfun is not None:
        if float(tolfun) <= 0.0:
            raise ValueError("tolfun must be > 0")
    remaining_evaluations = None if max_evaluations is None else int(max_evaluations)
    remaining_iterations = None if max_iter is None else int(max_iter)
    best_cost = math.inf
    best_candidate: np.ndarray | None = None
    stop_reasons: list[str] = []
    rng = np.random.default_rng(int(seed))

    for restart_index in range(int(restarts or 0) + 1):
        if remaining_evaluations is not None and remaining_evaluations <= 0:
            break
        if remaining_iterations is not None and remaining_iterations <= 0:
            break

        options: dict[str, object] = {
            "seed": int(seed) + restart_index,
            "verb_disp": 1 if verbose else 0,
            "verb_log": 0,
            "verb_filenameprefix": "",
        }
        if bool(normalize):
            options["bounds"] = [0.0, 1.0]
        else:
            options["bounds"] = [lower.tolist(), upper.tolist()]
        if popsize is not None:
            if int(popsize) <= 0:
                raise ValueError("popsize must be > 0")
            options["popsize"] = int(popsize)
        if remaining_iterations is not None:
            options["maxiter"] = int(remaining_iterations)
        if remaining_evaluations is not None:
            options["maxfevals"] = int(remaining_evaluations)
        if tolx is not None:
            options["tolx"] = float(tolx)
        if tolfun is not None:
            options["tolfun"] = float(tolfun)

        if restart_index == 0:
            restart_initial = initial.copy()
        elif best_candidate is not None:
            restart_initial = best_candidate.copy()
        elif bool(normalize):
            restart_initial = rng.uniform(0.0, 1.0, size=lower.size)
        else:
            restart_initial = rng.uniform(lower, upper, size=lower.size)

        before_evaluations = n_evaluations
        strategy = cma.CMAEvolutionStrategy(
            restart_initial.tolist(),
            sigma0_value,
            options,
        )
        while not strategy.stop():
            candidates = strategy.ask()
            costs = [_wrapped(candidate) for candidate in candidates]
            strategy.tell(candidates, costs)
            iteration_best_index = int(np.argmin(costs))
            iteration_best_cost = float(costs[iteration_best_index])
            if iteration_best_cost < best_cost:
                best_cost = iteration_best_cost
                best_candidate = np.asarray(
                    candidates[iteration_best_index],
                    dtype=float,
                )

        if best_candidate is None:
            best_candidate = np.asarray(strategy.result.xbest, dtype=float)
            best_cost = float(strategy.result.fbest)
        stop_reasons.extend(str(item) for item in strategy.stop().keys())

        evaluations_used = int(n_evaluations - before_evaluations)
        if remaining_evaluations is not None:
            remaining_evaluations = max(0, remaining_evaluations - evaluations_used)
        if remaining_iterations is not None:
            remaining_iterations = max(0, remaining_iterations - int(strategy.countiter))

    x_best = _to_physical(
        best_candidate,
        lower=lower,
        upper=upper,
        normalize=bool(normalize),
    )
    return CalibrationResults(
        method="cma_es",
        x_best=x_best,
        params_best=None,
        cost_best=float(best_cost),
        score_best=None,
        n_evaluations=int(n_evaluations),
        metadata={
            "sigma0": float(sigma0_value),
            "normalize": bool(normalize),
            "popsize": None if popsize is None else int(popsize),
            "max_iter": None if max_iter is None else int(max_iter),
            "max_evaluations": (
                None if max_evaluations is None else int(max_evaluations)
            ),
            "restarts": int(restarts),
            "stop_reasons": stop_reasons,
        },
    )
