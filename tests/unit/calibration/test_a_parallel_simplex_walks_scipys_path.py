"""A parallel Nelder-Mead walks SciPy's path, whatever its width.

``scipy_nelder_mead`` runs a port of SciPy 1.18.1's ``_minimize_neldermead``
(:mod:`hydromodpy.calibration.optim.nelder_mead`). Each step proposes the
candidates that depend only on the simplex it starts from, several at once under
``parallel``, and reads only the values SciPy's rules ask for.

What is gated here, against ``scipy.optimize.minimize(method="Nelder-Mead")``
called with the same initial simplex, options and clipped objective: the used
calls (point and value, in order), the final point, the call and iteration
counts, the status and ``success``, for widths 1, 2, 4 and 8 and values given
back in a shuffled order. Through the engine, a parallel run whose budget binds
ends where the sequential one ends, and the candidates it solved for nothing stay
in the history, marked.
"""

from __future__ import annotations

import random
from collections.abc import Callable

import numpy as np
import pytest
from scipy.optimize import minimize

from hydromodpy.calibration.optim.adapters.scipy_adapter import ScipyNelderMead
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.nelder_mead import SHRINK, SpeculativeNelderMead
from hydromodpy.calibration.optim.optimizer import (
    FAILED_EVAL_COST,
    EvaluationResult,
    ParamSuggestion,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.prior_sampling import transformed_prior_center

WIDTHS = (1, 2, 4, 8)


# --------------------------------------------------------------------------- #
# Analytic functions
# --------------------------------------------------------------------------- #


def _bowl(centre: tuple[float, ...], scale: tuple[float, ...] | None = None):
    c = np.asarray(centre, dtype=float)
    s = np.ones_like(c) if scale is None else np.asarray(scale, dtype=float)

    def f(x: np.ndarray) -> float:
        return float(np.sum(s * (x - c) ** 2))

    return f


def _rosenbrock(x: np.ndarray) -> float:
    return float(100.0 * (x[1] - x[0] ** 2) ** 2 + (1.0 - x[0]) ** 2)


def _plateau(x: np.ndarray) -> float:
    """Zero on a ball: the simplex ends on equal values and shrinks."""
    return float(max(0.0, np.linalg.norm(x - 0.2) - 0.3))


def _staircase(x: np.ndarray) -> float:
    """Piecewise constant: many equal values, so ``np.argsort`` breaks ties."""
    return float(np.floor(8.0 * np.sum((x - 0.1) ** 2)) / 8.0)


def _failed_outside_a_disk(x: np.ndarray) -> float:
    """The adapter's failure cost outside a disk, a bowl inside it."""
    if np.linalg.norm(x - 0.5) > 0.45:
        return FAILED_EVAL_COST
    return float(np.sum((x - 0.6) ** 2))


def _box(lower: tuple[float, ...], upper: tuple[float, ...]):
    return np.asarray(lower, dtype=float), np.asarray(upper, dtype=float)


def _adapter_simplex(x0: np.ndarray, lower: np.ndarray, upper: np.ndarray) -> np.ndarray:
    """The initial simplex ``ScipyNelderMead`` builds: 10 % of each range."""
    n = x0.size
    delta = 0.1 * (upper - lower)
    simplex = np.tile(x0, (n + 1, 1))
    for i in range(n):
        simplex[i + 1, i] = float(np.clip(x0[i] + delta[i], lower[i], upper[i]))
    return simplex


# name: (function, (lower, upper), x0 or None for the centre, options)
CASES: dict[str, tuple[Callable, tuple, tuple | None, dict]] = {
    "bowl_1d": (_bowl((0.3,)), _box((0.0,), (1.0,)), None, {"maxiter": 100, "maxfev": 100}),
    "bowl_2d": (
        _bowl((0.3, 0.5)),
        _box((0.0, -2.0), (1.0, 2.0)),
        None,
        {"maxiter": 100, "maxfev": 100},
    ),
    "bowl_2d_tight_tolerances": (
        _bowl((0.3, 0.5), (1.0, 30.0)),
        _box((0.0, -2.0), (1.0, 2.0)),
        None,
        {"maxiter": 300, "maxfev": 300, "xatol": 1e-9, "fatol": 1e-12},
    ),
    "bowl_beyond_a_bound": (
        _bowl((1.4, -0.5)),
        _box((0.0, -2.0), (1.0, 2.0)),
        None,
        {"maxiter": 200, "maxfev": 200},
    ),
    "bowl_4d": (
        _bowl((0.1, -0.2, 0.3, 0.05), (1.0, 2.0, 3.0, 4.0)),
        _box((-1.0,) * 4, (1.0,) * 4),
        None,
        {"maxiter": 400, "maxfev": 400},
    ),
    "rosenbrock": (
        _rosenbrock,
        _box((-2.0, -2.0), (2.0, 2.0)),
        (-1.2, 1.0),
        {"maxiter": 400, "maxfev": 400},
    ),
    "rosenbrock_not_adaptive": (
        _rosenbrock,
        _box((-2.0, -2.0), (2.0, 2.0)),
        (-1.2, 1.0),
        {"maxiter": 400, "maxfev": 400, "adaptive": False},
    ),
    "rosenbrock_scipy_defaults": (_rosenbrock, _box((-2.0, -2.0), (2.0, 2.0)), (-1.2, 1.0), {}),
    "rosenbrock_maxiter": (
        _rosenbrock,
        _box((-2.0, -2.0), (2.0, 2.0)),
        (-1.2, 1.0),
        {"maxiter": 15, "maxfev": 400},
    ),
    "plateau_3d": (_plateau, _box((-1.0,) * 3, (1.0,) * 3), None, {"maxiter": 300, "maxfev": 300}),
    "staircase": (
        _staircase,
        _box((-1.0, -1.0), (1.0, 1.0)),
        (0.7, -0.6),
        {"maxiter": 200, "maxfev": 200},
    ),
    "failed_outside_a_disk": (
        _failed_outside_a_disk,
        _box((0.0, 0.0), (1.0, 1.0)),
        (0.45, 0.4),
        {"maxiter": 200, "maxfev": 200},
    ),
    "start_on_the_upper_bound": (
        _bowl((0.3, 0.5)),
        _box((0.0, 0.0), (1.0, 1.0)),
        (1.0, 1.0),
        {"maxiter": 100, "maxfev": 100},
    ),
}


# --------------------------------------------------------------------------- #
# The two runs compared
# --------------------------------------------------------------------------- #


def _setup(name: str):
    f, (lower, upper), start, options = CASES[name]
    x0 = (lower + upper) / 2.0 if start is None else np.asarray(start, dtype=float)
    options = {"adaptive": True, **options}
    return f, lower, upper, x0, _adapter_simplex(x0, lower, upper), options


def _scipy(f, lower, upper, x0, simplex, options):
    calls: list[tuple[np.ndarray, float]] = []

    def objective(x: np.ndarray) -> float:
        value = f(np.clip(np.asarray(x, dtype=float), lower, upper))
        calls.append((np.array(x, copy=True), value))
        return value

    result = minimize(
        objective,
        x0,
        method="Nelder-Mead",
        options={**options, "initial_simplex": simplex},
    )
    return result, calls


def _speculative(f, lower, upper, x0, simplex, options, width: int, seed: int = 0):
    """Drive the port with *width* proposals per round, values given back shuffled."""
    rng = random.Random(seed)
    simplex_run = SpeculativeNelderMead(x0, initial_simplex=simplex, **options)
    proposed = []
    while batch := simplex_run.propose(width):
        assert len(batch) <= width
        proposed.extend(p.key for p in batch)
        rng.shuffle(batch)
        for p in batch:
            simplex_run.receive(p.key, f(np.clip(p.point, lower, upper)))
    return simplex_run, proposed


def _assert_same_run(simplex_run, result, calls) -> None:
    used = simplex_run.used
    assert len(used) == len(calls)
    for step, (call, (point, value)) in enumerate(zip(used, calls, strict=True)):
        assert np.array_equal(call.point, point), f"call {step} differs"
        assert call.value == value, f"call {step} differs"
    mine = simplex_run.result
    assert mine is not None
    assert np.array_equal(mine.x, result.x)
    assert mine.fun == result.fun
    assert mine.nfev == result.nfev
    assert mine.nit == result.nit
    assert mine.status == result.status
    assert mine.success == result.success


# --------------------------------------------------------------------------- #
# The port against SciPy
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("name", sorted(CASES))
def test_the_port_reads_scipys_calls_and_ends_where_scipy_ends(name: str, width: int) -> None:
    f, lower, upper, x0, simplex, options = _setup(name)
    result, calls = _scipy(f, lower, upper, x0, simplex, options)

    simplex_run, proposed = _speculative(f, lower, upper, x0, simplex, options, width)

    _assert_same_run(simplex_run, result, calls)
    fates = {key: simplex_run.fate(key) for key in proposed}
    assert "open" not in fates.values()
    assert sum(fate == "used" for fate in fates.values()) == result.nfev
    if width == 1:
        # One point at a time proposes exactly SciPy's calls, nothing more.
        assert len(proposed) == result.nfev
    elif result.nit > 3:
        # A wider width did speculate, and still read only SciPy's calls.
        assert len(proposed) > result.nfev


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("maxfev", range(1, 26))
def test_maxfev_cuts_the_run_at_the_same_call(maxfev: int, width: int) -> None:
    # Every cut from inside the initial simplex to the middle of a shrink.
    f, lower, upper, x0, simplex, options = _setup("plateau_3d")
    options = {**options, "maxfev": maxfev}
    result, calls = _scipy(f, lower, upper, x0, simplex, options)

    simplex_run, _proposed = _speculative(f, lower, upper, x0, simplex, options, width)

    _assert_same_run(simplex_run, result, calls)
    assert result.nfev == maxfev
    assert not simplex_run.result.success


@pytest.mark.parametrize("name", ["plateau_3d", "staircase", "rosenbrock", "rosenbrock_maxiter"])
def test_the_cases_reach_the_rules_they_are_named_for(name: str) -> None:
    f, lower, upper, x0, simplex, options = _setup(name)
    simplex_run, _proposed = _speculative(f, lower, upper, x0, simplex, options, 1)
    roles = [call.key[1] for call in simplex_run.used]
    if name in ("plateau_3d", "staircase"):
        assert SHRINK in roles
    if name == "rosenbrock":
        assert simplex_run.result.success
    if name == "rosenbrock_maxiter":
        assert simplex_run.result.status == 2


def test_a_value_is_given_back_once_for_a_proposed_point() -> None:
    simplex_run = SpeculativeNelderMead(np.array([0.5]), adaptive=True)
    (proposal,) = simplex_run.propose(1)
    with pytest.raises(ValueError, match="never proposed"):
        simplex_run.receive((0, "vertex", 1), 1.0)
    simplex_run.receive(proposal.key, 1.0)
    with pytest.raises(ValueError, match="already has a value"):
        simplex_run.receive(proposal.key, 1.0)


# --------------------------------------------------------------------------- #
# The adapter against SciPy
# --------------------------------------------------------------------------- #

SPACE = ParameterSpace(
    [
        CalibParameter(name="K", lower=1e-7, upper=1e-3, transform="log"),
        CalibParameter(name="Sy", lower=0.01, upper=0.3),
    ]
)


def _misfit(values) -> float:
    return float((np.log10(values["K"]) + 4.3) ** 2 + 20.0 * (values["Sy"] - 0.12) ** 2)


def _physical(point: np.ndarray) -> dict[str, float]:
    return {p.name: p.to_physical(float(point[i])) for i, p in enumerate(SPACE.parameters)}


def _scipy_through_the_adapter_objective(maxiter: int, xatol: float | None):
    """SciPy run as the adapter set it up before it walked the port."""
    lower = np.array([p.lower_transformed for p in SPACE.parameters])
    upper = np.array([p.upper_transformed for p in SPACE.parameters])
    x0 = transformed_prior_center(SPACE)
    options = {"maxiter": maxiter, "maxfev": maxiter, "adaptive": True}
    if xatol is not None:
        options["xatol"] = xatol
    visited: list[tuple[dict[str, float], float]] = []

    def objective(x: np.ndarray) -> float:
        values = _physical(np.clip(np.asarray(x, dtype=float), lower, upper))
        cost = _misfit(values)
        visited.append((values, cost))
        return cost

    result = minimize(
        objective,
        x0,
        method="Nelder-Mead",
        options={**options, "initial_simplex": _adapter_simplex(x0, lower, upper)},
    )
    return result, visited


@pytest.mark.parametrize("width", WIDTHS)
def test_the_adapter_reads_scipys_trials_in_scipys_order(width: int) -> None:
    result, visited = _scipy_through_the_adapter_objective(200, 1e-6)
    optimizer = ScipyNelderMead(SPACE, maxiter=200, xatol=1e-6)
    told: list[tuple[ParamSuggestion, EvaluationResult]] = []
    while batch := optimizer.ask(width):
        results = [
            EvaluationResult(trial_id=s.trial_id, sim_id=None, objective_value=_misfit(s.values))
            for s in batch
        ]
        # The order values come back in changes nothing.
        optimizer.tell(results[::-1])
        told.extend(zip(batch, results, strict=True))

    used = [(s, r) for s, r in told if not r.metadata.get("speculative_unused")]
    assert [(dict(s.values), r.objective_value) for s, r in used] == visited
    assert optimizer.converged() == result.success
    best = optimizer.best()
    assert best is not None
    assert best.objective_value == min(cost for _values, cost in visited)
    if width == 1:
        assert len(told) == len(visited)


# --------------------------------------------------------------------------- #
# Through the engine
# --------------------------------------------------------------------------- #


def _evaluate(sugg: ParamSuggestion) -> EvaluationResult:
    return EvaluationResult(
        trial_id=sugg.trial_id, sim_id=None, objective_value=_misfit(sugg.values)
    )


def _engine_run(parallel: int, max_iter: int):
    values_of: dict[int, dict[str, float]] = {}
    session = CalibrationEngine(
        space=SPACE,
        optimizer=ScipyNelderMead(SPACE, maxiter=200, xatol=1e-6),
        evaluator=_evaluate,
        max_iter=max_iter,
        parallel=parallel,
        on_iteration=lambda sugg, _result: values_of.__setitem__(sugg.trial_id, dict(sugg.values)),
    ).run()
    used = [r for r in session.history if not r.metadata.get("speculative_unused")]
    unused = [r for r in session.history if r.metadata.get("speculative_unused")]
    path = [
        (values_of[r.trial_id], r.objective_value) for r in sorted(used, key=lambda r: r.trial_id)
    ]
    return session, values_of, used, unused, path


@pytest.mark.parametrize("max_iter", [7, 25, 200])
def test_a_parallel_run_ends_where_the_sequential_one_ends(max_iter: int) -> None:
    sequential, seq_values, seq_used, seq_unused, seq_path = _engine_run(1, max_iter)
    parallel, par_values, par_used, par_unused, par_path = _engine_run(4, max_iter)

    assert not seq_unused
    assert par_path == seq_path
    assert len(par_used) == len(seq_used) == len(sequential.history)
    assert parallel.converged == sequential.converged
    assert par_values[parallel.best.trial_id] == seq_values[sequential.best.trial_id]
    assert parallel.best.objective_value == sequential.best.objective_value
    # The candidates solved for nothing are real solves: kept, and marked.
    assert par_unused
    assert len(parallel.history) == len(par_used) + len(par_unused)
    if max_iter < 200:
        # The budget binds: both stop on it, after exactly max_iter counted trials.
        assert len(seq_used) == max_iter
        assert not sequential.converged
    else:
        assert sequential.converged
        assert len(seq_used) < max_iter
