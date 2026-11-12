"""Parallel Nelder-Mead, a port of SciPy's simplex search.

The port proposes several candidates at once and reads only the values SciPy's
rules ask for. It is held against `scipy.optimize.minimize(method="Nelder-Mead")`
for widths 1, 2, 4 and 8, then through the engine. Costs are dimensionless.
"""

from __future__ import annotations

import random
from collections.abc import Callable

import numpy as np
import pytest
from scipy.optimize import minimize

from hydromodpy.calibration.optim.adapters.scipy_adapter import ScipyNelderMead
from hydromodpy.calibration.optim.nelder_mead import SpeculativeNelderMead
from hydromodpy.calibration.optim.optimizer import (
    FAILED_EVAL_COST,
    EvaluationResult,
    ParamSuggestion,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from tests.unit.calibration._factories_search import run_engine

WIDTHS = (1, 2, 4, 8)


# Analytic functions
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


# name: (function, (lower, upper), x0 or None for the center, options)
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


# The two runs compared
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
        objective, x0, method="Nelder-Mead", options={**options, "initial_simplex": simplex}
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


# The port against SciPy
@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("name", sorted(CASES))
def test_port_matches_scipy(name: str, width: int) -> None:
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


@pytest.mark.parametrize(
    ("x0", "options"),
    [
        ((0.0, 0.5), {}),
        ((0.9, 0.1), {"maxiter": 15}),
        ((0.9, 0.1), {"maxfev": 15}),
        ((0.9, 0.1), {"maxfev": np.inf}),
        ((0.9, 0.1), {"maxiter": np.inf}),
    ],
    ids=["zero-component", "maxiter-only", "maxfev-only", "maxfev-inf", "maxiter-inf"],
)
def test_default_simplex_and_limits(x0, options) -> None:
    f, lower, upper = _bowl((0.3, 0.6)), np.zeros(2), np.ones(2)
    x0 = np.asarray(x0)
    result, calls = _scipy(f, lower, upper, x0, None, options)

    simplex_run, _ = _speculative(f, lower, upper, x0, None, options, 1)

    _assert_same_run(simplex_run, result, calls)
    assert simplex_run.finished


@pytest.mark.parametrize(
    ("simplex", "message"),
    [
        (np.zeros((3, 3)), r"shape \(N\+1,N\)"),
        (np.zeros((3, 2)), "not consistent with `x0`"),
    ],
)
def test_wrong_simplex_shape(simplex, message) -> None:
    x0 = np.zeros(2 if message.startswith("shape") else 3)

    with pytest.raises(ValueError, match=message):
        SpeculativeNelderMead(x0, initial_simplex=simplex)


def test_no_call_left() -> None:
    simplex_run = SpeculativeNelderMead(np.array([0.5, 0.2]), maxfev=0)

    assert simplex_run.finished
    assert simplex_run.propose(2) == []
    assert (simplex_run.result.nfev, simplex_run.result.status) == (0, 1)


def test_value_given_back_once() -> None:
    simplex_run = SpeculativeNelderMead(np.array([0.5]), adaptive=True)
    (proposal,) = simplex_run.propose(1)
    with pytest.raises(ValueError, match="never proposed"):
        simplex_run.receive((0, "vertex", 1), 1.0)
    simplex_run.receive(proposal.key, 1.0)
    with pytest.raises(ValueError, match="already has a value"):
        simplex_run.receive(proposal.key, 1.0)


def _finish(run: SpeculativeNelderMead, f: Callable) -> SpeculativeNelderMead:
    while batch := run.propose(1):
        run.receive(batch[0].key, f(batch[0].point))
    return run


@pytest.mark.parametrize(
    ("x0", "simplex", "dtype"),
    [
        (np.array([1, 2]), None, np.float64),
        (np.array([1, 2], dtype=np.float32), None, np.float32),
        (np.array([0.5, 0.5]), np.array([[0, 0], [1, 0], [0, 1]]), np.float64),
        (np.array([0.5, 0.5]), np.array([[0, 0], [1, 0], [0, 1]], dtype=np.float32), np.float32),
    ],
    ids=["int_start", "float32_start", "int_simplex", "float32_simplex"],
)
def test_float_type_and_copies(x0, simplex, dtype) -> None:
    run = _finish(
        SpeculativeNelderMead(x0, initial_simplex=simplex, maxfev=6), lambda x: float(np.sum(x**2))
    )

    result = run.result
    assert result.x.dtype == result.final_simplex[0].dtype == dtype
    assert not np.shares_memory(result.x, result.final_simplex[0])


@pytest.mark.parametrize(
    ("options", "nfev", "nit"),
    [({}, 400, 200), ({"maxfev": np.inf}, 799, 400), ({"maxiter": np.inf}, 400, 200)],
    ids=["both_unset", "maxfev_inf", "maxiter_inf"],
)
def test_default_call_limit(options, nfev, nit) -> None:
    # A function that falls forever never meets a tolerance: only the limits stop it.
    run = SpeculativeNelderMead(np.zeros(2), **options)

    _finish(run, lambda x: -float(np.sum(x)))

    assert (run.result.nfev, run.result.nit) == (nfev, nit)
    assert not run.result.success


def _roles_proposed_after_the_vertices(simplex, costs, width=10, fxr=None, **options):
    """Give the vertex costs, then the reflection cost, and list what is proposed next."""
    run = SpeculativeNelderMead(simplex[0], initial_simplex=np.array(simplex), **options)
    for cost in costs:
        run.receive(run.propose(1)[0].key, cost)
    if fxr is not None:
        run.receive(run.propose(1)[0].key, fxr)
    return [p.key[1] for p in run.propose(width)]


@pytest.mark.parametrize(
    ("maxfev", "roles"),
    [
        (3, ["reflection"]),
        (4, ["reflection", "inside_contraction", "expansion", "outside_contraction"]),
        (5, ["reflection", "inside_contraction", "expansion", "outside_contraction", "shrink"]),
    ],
)
def test_budget_limits_proposals(maxfev, roles) -> None:
    # One dimension, two calls spent: the reflection needs 1 call, the contractions and the
    # expansion 2, the shrink point 3.
    assert _roles_proposed_after_the_vertices([[0.0], [1.0]], [0.0, 10.0], maxfev=maxfev) == roles


# Through the engine
SPACE = ParameterSpace(
    [
        CalibParameter(name="K", lower=1e-7, upper=1e-3, search_space="log"),
        CalibParameter(name="Sy", lower=0.01, upper=0.3),
    ]
)


def _misfit(values) -> float:
    return float((np.log10(values["K"]) + 4.3) ** 2 + 20.0 * (values["Sy"] - 0.12) ** 2)


def _evaluate(sugg: ParamSuggestion) -> EvaluationResult:
    return EvaluationResult(trial_id=sugg.trial_id, sim_id=None, cost=_misfit(sugg.values))


def _engine_run(parallel: int, max_trials: int):
    values_of: dict[int, dict[str, float]] = {}
    session = run_engine(
        SPACE,
        ScipyNelderMead(SPACE, maxiter=200, xatol=1e-6),
        _evaluate,
        max_trials,
        parallel=parallel,
        on_iteration=lambda sugg, _result: values_of.__setitem__(sugg.trial_id, dict(sugg.values)),
    )
    used = [r for r in session.history if not r.metadata.get("speculative_unused")]
    unused = [r for r in session.history if r.metadata.get("speculative_unused")]
    path = [(values_of[r.trial_id], r.cost) for r in sorted(used, key=lambda r: r.trial_id)]
    return session, values_of, used, unused, path


@pytest.mark.parametrize("max_trials", [7, 25, 200])
def test_parallel_ends_with_sequential(max_trials: int) -> None:
    sequential, seq_values, seq_used, seq_unused, seq_path = _engine_run(1, max_trials)
    parallel, par_values, par_used, par_unused, par_path = _engine_run(4, max_trials)

    assert not seq_unused
    assert par_path == seq_path
    assert len(par_used) == len(seq_used) == len(sequential.history)
    assert parallel.converged == sequential.converged
    assert par_values[parallel.best.trial_id] == seq_values[sequential.best.trial_id]
    assert parallel.best.cost == sequential.best.cost
    # The candidates solved for nothing are real solves: kept, and marked.
    assert par_unused
    assert len(parallel.history) == len(par_used) + len(par_unused)
    if max_trials < 200:
        # The budget binds: both stop on it, after exactly max_trials counted trials.
        assert len(seq_used) == max_trials
        assert not sequential.converged
    else:
        assert sequential.converged
        assert len(seq_used) < max_trials
