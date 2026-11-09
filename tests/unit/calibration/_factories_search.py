"""Helpers shared by the criteria, evaluation and optim tests."""

from __future__ import annotations

import math

from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace


def make_space(*specs: tuple) -> ParameterSpace:
    """Build a space from ``(name, lower, upper)`` or ``(name, lower, upper, search_space)``."""
    return ParameterSpace(
        [
            CalibParameter(
                name=name, lower=lower, upper=upper, **({"search_space": s[0]} if s else {})
            )
            for name, lower, upper, *s in specs
        ]
    )


def staircase(root: float, value: float, per_decade: float = 20.0) -> float:
    """A residual that is positive below ``root``, negative above, and never zero."""
    return (math.floor(math.log10(root / value) * per_decade) + 0.5) / per_decade


def run_engine(space, optimizer, evaluator, max_trials, **options):
    """Run a calibration engine to its end and return the session."""
    return CalibrationEngine(
        space=space, optimizer=optimizer, evaluator=evaluator, max_trials=max_trials, **options
    ).run()


def result_of(suggestion, cost: float, **fields) -> EvaluationResult:
    """The completed result of a trial, with ``fields`` (components, metadata...) added."""
    return EvaluationResult(
        trial_id=suggestion.trial_id, sim_id=None, cost=cost, **{"status": "completed", **fields}
    )
