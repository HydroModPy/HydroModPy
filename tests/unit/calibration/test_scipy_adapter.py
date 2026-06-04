"""Behavioural unit tests for the SciPy optimizer adapters.

Covers :mod:`hydromodpy.calibration.adapters.scipy_adapter`
(``scipy_de`` and ``scipy_nelder_mead``), which bridge SciPy's push-style
``differential_evolution`` / ``minimize`` API to the ask/tell Protocol via a
background worker thread and a pair of queues.

Focus:

- ``ask(n>1)`` on the sequential SciPy adapters returns only the points that
  are already available and never blocks (regression for a deadlock where the
  worker is blocked waiting for the previous ``tell``);
- ``close`` is cancel-safe when the loop exits on its budget before the
  optimizer converges (the worker terminates, no thread is left blocked);
- DE / Nelder-Mead drive a convex quadratic to its known minimum, seeded
  reproducibly;
- ``tell`` of a failed/NaN evaluation maps to ``FAILED_EVAL_COST`` and never
  poisons the run;
- only ``scipy_de`` / ``scipy_nelder_mead`` are registered, not ``scipy``.
"""

from __future__ import annotations

import math

from hydromodpy.calibration.adapters.scipy_adapter import ScipyDE, ScipyNelderMead
from hydromodpy.calibration.optimizer import (
    FAILED_EVAL_COST,
    EvaluationResult,
    build_optimizer,
)
from hydromodpy.calibration.parameters import CalibParameter, ParameterSpace

_TARGET = {"x": 0.3, "y": 0.5}


def _two_dim_space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=0.0, upper=1.0),
            CalibParameter(name="y", lower=-2.0, upper=2.0),
        ]
    )


def _quadratic_cost(values) -> float:
    """Convex bowl centred on ``_TARGET`` with a unique minimum of 0."""
    return float((values["x"] - _TARGET["x"]) ** 2 + (values["y"] - _TARGET["y"]) ** 2)


def _make_result(sugg, cost: float, status: str = "completed") -> EvaluationResult:
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        objective_value=cost,
        status=status,
    )


def _drive(opt, cost_fn=_quadratic_cost, ask_n: int = 1, guard: int = 20000):
    """Drive a full ask/tell loop to convergence. Return the running best costs."""
    best_curve: list[float] = []
    running = math.inf
    loops = 0
    while not opt.converged() and loops < guard:
        loops += 1
        batch = opt.ask(ask_n)
        if not batch:
            break
        results = []
        for sugg in batch:
            cost = cost_fn(sugg.values)
            running = min(running, cost)
            results.append(_make_result(sugg, cost))
        opt.tell(results)
        best_curve.append(running)
    return best_curve


# ---------------------------------------------------------------------------
# Deadlock regression: batched ask on a sequential adapter
# ---------------------------------------------------------------------------


def test_de_ask_batch_returns_available_without_blocking() -> None:
    opt = ScipyDE(_two_dim_space(), seed=0, maxiter=10, popsize=5)
    try:
        # The previous implementation blocked forever here: a sequential DE
        # (workers=1) produces the next point only after the current one is
        # told, so the second blocking ``get`` never returned.
        batch = opt.ask(5)
        assert 1 <= len(batch) <= 5
        # The single ready point is a real, in-bounds suggestion.
        first = batch[0]
        assert set(first.values) == {"x", "y"}
        assert 0.0 <= first.values["x"] <= 1.0
        assert -2.0 <= first.values["y"] <= 2.0
        opt.tell([_make_result(s, _quadratic_cost(s.values)) for s in batch])
    finally:
        opt.close()


def test_nelder_mead_ask_batch_returns_available_without_blocking() -> None:
    opt = ScipyNelderMead(_two_dim_space(), seed=0, maxiter=10)
    try:
        batch = opt.ask(4)
        assert 1 <= len(batch) <= 4
        opt.tell([_make_result(s, _quadratic_cost(s.values)) for s in batch])
    finally:
        opt.close()


# ---------------------------------------------------------------------------
# Cancel-safe close
# ---------------------------------------------------------------------------


def test_close_is_cancel_safe_after_early_exit() -> None:
    """Exiting the loop before convergence and closing must not leave a worker
    blocked on the next ``tell``."""
    opt = ScipyDE(_two_dim_space(), seed=0, maxiter=100, popsize=15, tol=1e-9)
    for _ in range(5):
        batch = opt.ask(1)
        assert batch
        opt.tell([_make_result(s, _quadratic_cost(s.values)) for s in batch])
    assert not opt.converged()  # budget intentionally not exhausted
    opt.close()
    # The background worker really terminated (no deadlocked thread survives).
    assert not opt._bridge._thread.is_alive()
    # close is idempotent.
    opt.close()


# ---------------------------------------------------------------------------
# Convergence on a convex quadratic
# ---------------------------------------------------------------------------


def test_de_converges_to_known_minimum() -> None:
    opt = ScipyDE(_two_dim_space(), seed=1, maxiter=60, popsize=10, tol=1e-7)
    try:
        curve = _drive(opt, ask_n=4)
        assert curve  # at least one generation ran
        best = opt.best()
        assert best is not None
        assert best.objective_value < 1e-3
        assert curve[-1] <= curve[0]  # running best never increases
    finally:
        opt.close()


def test_nelder_mead_converges_to_known_minimum() -> None:
    opt = ScipyNelderMead(_two_dim_space(), seed=0, maxiter=200)
    try:
        _drive(opt, ask_n=3)
        best = opt.best()
        assert best is not None
        assert best.objective_value < 1e-4
    finally:
        opt.close()


def test_de_seed_is_reproducible() -> None:
    runs = []
    for _ in range(2):
        opt = ScipyDE(_two_dim_space(), seed=7, maxiter=40, popsize=8, tol=1e-7)
        try:
            _drive(opt, ask_n=1)
            runs.append(opt.best().objective_value)
        finally:
            opt.close()
    assert runs[0] == runs[1]


# ---------------------------------------------------------------------------
# tell semantics
# ---------------------------------------------------------------------------


def test_best_is_none_before_any_completed_eval() -> None:
    opt = ScipyDE(_two_dim_space(), seed=0, maxiter=5, popsize=5)
    try:
        assert opt.best() is None
    finally:
        opt.close()


def test_failed_eval_maps_to_failed_cost_and_is_excluded_from_best() -> None:
    opt = ScipyDE(_two_dim_space(), seed=0, maxiter=20, popsize=6, tol=1e-9)
    try:
        first = True
        for _ in range(12):
            batch = opt.ask(1)
            if not batch:
                break
            results = []
            for sugg in batch:
                if first:
                    # First evaluation fails: must not poison the optimizer.
                    results.append(_make_result(sugg, float("nan"), status="failed"))
                    first = False
                else:
                    results.append(_make_result(sugg, _quadratic_cost(sugg.values)))
            opt.tell(results)
        best = opt.best()
        # best() only ever returns a completed evaluation, never the failure.
        assert best is not None
        assert best.status == "completed"
        assert best.objective_value < FAILED_EVAL_COST
    finally:
        opt.close()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registered_names() -> None:
    assert isinstance(build_optimizer("scipy_de", _two_dim_space(), seed=0), ScipyDE)
    nm = build_optimizer("scipy_nelder_mead", _two_dim_space(), seed=0)
    assert isinstance(nm, ScipyNelderMead)
    build_optimizer("scipy_de", _two_dim_space(), seed=0).close()
    nm.close()
