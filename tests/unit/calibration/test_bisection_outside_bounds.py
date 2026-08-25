"""A root found outside the declared bounds says something about the prior.

The search widens its bracket a decade at a time, which is what lets it find a
sign change a cautious prior missed. Several decades out is a different matter:
it is usually the residual failing to respond to the parameter at all. Measured
on the Nancon with the streams in SFR, the simulated network holds the reaches
by construction whatever the conductivity, the residual stays positive across
the whole declared interval, and the search closes three decades above it on a
value that means nothing while roptim reports 1.5, inside its validity bound.
"""

from __future__ import annotations

import logging
import math

from hydromodpy.calibration.adapters.bisection_adapter import BisectionAdapter
from hydromodpy.calibration.optim.optimizer import EvaluationResult
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace


def _space(lower: float = 1.0, upper: float = 1.0e3) -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="K", lower=lower, upper=upper, transform="log")])


def _evaluate(suggestion, *, root: float) -> EvaluationResult:
    value = float(next(iter(suggestion.values.values())))
    steps = math.floor(math.log10(root / value) * 20.0) + 0.5
    residual = steps / 20.0
    return EvaluationResult(
        trial_id=suggestion.trial_id,
        sim_id=None,
        objective_value=abs(residual),
        status="completed",
        components={"net.J_signed": residual, "net.J": abs(residual)},
    )


def _run(adapter: BisectionAdapter, *, root: float, max_iter: int = 60) -> None:
    seen = 0
    while seen < max_iter:
        suggestions = adapter.ask(n=1)
        if not suggestions:
            return
        results = [_evaluate(s, root=root) for s in suggestions]
        seen += len(results)
        adapter.tell(results)
        if adapter.converged():
            return


def test_a_root_inside_the_bounds_says_nothing(caplog) -> None:
    adapter = BisectionAdapter(_space(), sweep_points=5, bracket_expand=4)
    _run(adapter, root=50.0)
    with caplog.at_level(logging.WARNING):
        adapter.best()

    assert "OUTSIDE the declared bounds" not in caplog.text


def test_a_root_above_the_declared_interval_is_reported(caplog) -> None:
    # The zero sits two decades above the declared upper bound, which the
    # search only reaches by expanding.
    adapter = BisectionAdapter(_space(), sweep_points=5, bracket_expand=4)
    _run(adapter, root=1.0e5)
    with caplog.at_level(logging.WARNING):
        winner = adapter.best()

    assert winner is not None
    assert "OUTSIDE the declared bounds" in caplog.text
    assert "does not respond to this parameter" in caplog.text
    assert "n_excess" in caplog.text


def test_a_bracket_that_never_expanded_is_never_reported(caplog) -> None:
    adapter = BisectionAdapter(_space(), sweep_points=5, bracket_expand=0)
    _run(adapter, root=50.0)
    with caplog.at_level(logging.WARNING):
        adapter.best()

    assert "OUTSIDE the declared bounds" not in caplog.text


def test_nothing_evaluated_means_nothing_to_report() -> None:
    adapter = BisectionAdapter(_space(), sweep_points=3, bracket_expand=0)
    assert adapter.best() is None
