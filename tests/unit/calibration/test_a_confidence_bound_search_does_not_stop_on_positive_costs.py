"""A gp_mapping search on a lower confidence bound judges the bound, not an EI.

With ``kappa != 0`` the acquisition is the negated lower confidence bound.
For positive costs that score is negative, so reading it as an expected
improvement made the search "converge" after ``ei_patience`` proposals.
"""

from __future__ import annotations

import sklearn  # noqa: F401

from hydromodpy.calibration.optim.optimizer import EvaluationResult, build_optimizer
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace


def _space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="x", lower=-2.0, upper=2.0),
            CalibParameter(name="y", lower=-2.0, upper=2.0),
        ]
    )


def _cost(values: dict) -> float:
    return 10.0 + float(values["x"]) ** 2 + float(values["y"]) ** 2


def _tell(opt, sugg) -> None:
    opt.tell(
        [
            EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=None,
                objective_value=_cost(sugg.values),
                status="completed",
            )
        ]
    )


def test_a_confidence_bound_search_does_not_stop_after_three_proposals():
    opt = build_optimizer("gp_mapping", _space(), seed=11, n_init=4, max_trials=20, kappa=1.5)
    n_init = 4
    for _ in range(n_init + 3):
        (sugg,) = opt.ask(1)
        _tell(opt, sugg)
    assert not opt.converged()


def test_a_confidence_bound_search_stops_once_the_bound_promises_nothing():
    opt = build_optimizer(
        "gp_mapping", _space(), seed=11, n_init=4, max_trials=60, kappa=1.5, ei_tol=1e6
    )
    for _ in range(60):
        got = opt.ask(1)
        if not got:
            break
        _tell(opt, got[0])
        if opt.converged():
            break
    assert opt.converged()
    assert len(opt._x_history) < 60


def test_the_confidence_bound_score_is_the_improvement_it_promises():
    opt = build_optimizer("gp_mapping", _space(), seed=11, n_init=4, max_trials=20, kappa=1.5)
    for _ in range(5):
        (sugg,) = opt.ask(1)
        _tell(opt, sugg)
    (sugg,) = opt.ask(1)
    assert opt._last_ei >= 0.0
