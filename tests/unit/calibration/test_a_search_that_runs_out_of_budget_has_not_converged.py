"""A search that stops on its budget before its own rule has not converged.

The engine used to leave its loop on ``max_iter`` without a word, and a staged
calibration froze whatever the last trial was. Now an engine that declares a
stopping rule gets one extension of half its budget, with a warning; if the rule
is still not met the session says so, the report records it, nothing is frozen
from the phase, and a phase that depends on it is refused.
"""

from __future__ import annotations

import logging
import math
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.adapters.bisection_adapter import (
    BisectionAdapter,
    evaluations_to_close_the_bracket,
)
from hydromodpy.calibration.optim.adapters.scipy_adapter import ScipyNelderMead
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import BUDGET_RULE, budget_extension, stopping_rule
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.cli_runner import (
    _search_outcome_extra,
    _status_of_the_search,
)
from hydromodpy.calibration.runners.staged_runner import (
    _converged,
    _frozen_by,
    _require_result_for_dependents,
)
from hydromodpy.core.exceptions import CalibrationError


def _log_space(lower: float = 1.0, upper: float = 1.0e3) -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="K", lower=lower, upper=upper, transform="log")])


def _root_at(root: float):
    """A continuous residual, positive below *root* and negative above it."""

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        residual = math.log10(root) - math.log10(float(sugg.values["K"]))
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=abs(residual),
            status="completed",
            components={"net.J_signed": residual},
        )

    return evaluate


def _bisection(**kwargs) -> BisectionAdapter:
    return BisectionAdapter(_log_space(), sweep_points=5, **kwargs)


# --------------------------------------------------------------------------- #
# How much the root search needs, known before the first solve
# --------------------------------------------------------------------------- #


def test_the_nancon_session_needed_fifteen_evaluations() -> None:
    assert evaluations_to_close_the_bracket(1e-7, 1e-3, rel_tol=0.01, sweep_points=7) == 15


def test_a_pure_bisection_starts_from_the_two_bounds() -> None:
    # One decade, 1 %: ceil(log2(1 / log10(1.01))) = 8 halvings after 2 bounds.
    assert evaluations_to_close_the_bracket(1.0, 10.0, rel_tol=0.01, sweep_points=0) == 10


def test_a_sweep_finer_than_the_tolerance_needs_no_halving() -> None:
    assert evaluations_to_close_the_bracket(1.0, 1.001, rel_tol=0.01, sweep_points=3) == 3


def test_bounds_that_are_not_a_positive_interval_are_refused() -> None:
    with pytest.raises(ValueError, match="0 < lower < upper"):
        evaluations_to_close_the_bracket(0.0, 1.0)
    with pytest.raises(ValueError, match="rel_tol"):
        evaluations_to_close_the_bracket(1.0, 10.0, rel_tol=0.0)


def test_the_count_is_what_the_search_actually_spends() -> None:
    adapter = _bisection()
    engine = CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=_root_at(50.0), max_iter=100
    )
    session = engine.run()

    assert session.converged
    assert len(session.history) == adapter.evaluations_needed == 13


def test_a_short_budget_is_announced_before_the_first_solve(caplog) -> None:
    adapter = _bisection()
    engine = CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=_root_at(50.0), max_iter=4
    )
    with caplog.at_level(logging.WARNING):
        engine.run()

    first = next(record for record in caplog.records if "max_iter = 4" in record.message)
    assert "13 evaluations" in first.message
    assert "Even the one-time extension to 6 will not" in first.message


def test_a_sufficient_budget_says_nothing_at_start(caplog) -> None:
    adapter = _bisection()
    engine = CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=_root_at(50.0), max_iter=13
    )
    with caplog.at_level(logging.WARNING):
        session = engine.run()

    assert session.converged
    assert session.extension == 0
    assert "max_iter =" not in caplog.text


# --------------------------------------------------------------------------- #
# One extension, then an honest verdict
# --------------------------------------------------------------------------- #


def test_the_extension_is_half_the_declared_budget() -> None:
    assert budget_extension(48) == 24
    assert budget_extension(5) == 3
    assert budget_extension(0) == 0


def test_an_engine_with_a_rule_names_it_and_a_budget_engine_does_not() -> None:
    assert stopping_rule(_bisection()) == "rel_tol"
    assert stopping_rule(build_optimizer("random_search", _log_space(), seed=1)) == BUDGET_RULE


def test_one_extension_that_closes_the_bracket_converges(caplog) -> None:
    adapter = _bisection()
    engine = CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=_root_at(50.0), max_iter=10
    )
    with caplog.at_level(logging.WARNING):
        session = engine.run()

    assert session.converged
    assert session.extension == 5
    assert len(session.history) == 13
    assert "Granting 5 more, once" in caplog.text


def test_a_search_still_open_after_the_extension_has_not_converged(caplog) -> None:
    adapter = _bisection()
    engine = CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=_root_at(50.0), max_iter=6
    )
    with caplog.at_level(logging.WARNING):
        session = engine.run()

    assert not session.converged
    assert session.extension == 3
    assert len(session.history) == 9
    assert caplog.text.count("Granting") == 1
    assert "did NOT converge" in caplog.text
    assert "Raise max_iter or loosen the tolerance" in caplog.text


def test_a_budget_engine_converges_when_it_spends_its_budget(caplog) -> None:
    optimizer = build_optimizer("random_search", _log_space(), seed=3)
    engine = CalibrationEngine(
        space=_log_space(), optimizer=optimizer, evaluator=_root_at(50.0), max_iter=4
    )
    with caplog.at_level(logging.WARNING):
        session = engine.run()

    assert session.converged
    assert session.extension == 0
    assert len(session.history) == 4
    assert "Granting" not in caplog.text


# --------------------------------------------------------------------------- #
# What the report and the staged runner do with it
# --------------------------------------------------------------------------- #


def test_the_report_records_the_verdict_and_the_open_bracket() -> None:
    adapter = _bisection()
    session = CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=_root_at(50.0), max_iter=6
    ).run()

    extra = _search_outcome_extra(session)

    assert extra["search"] == {
        "converged": False,
        "stopping_rule": "rel_tol",
        "max_iter": 6,
        "extension": 3,
        "n_evaluations": 9,
    }
    bracket = extra["bracket"]
    assert bracket["parameter"] == "K"
    assert bracket["closed"] is False
    assert bracket["low"] < 50.0 < bracket["high"]
    assert bracket["relative_width"] > 0.01


def test_the_report_publishes_the_closed_bracket_in_physical_units() -> None:
    adapter = _bisection()
    session = CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=_root_at(50.0), max_iter=20
    ).run()

    bracket = _search_outcome_extra(session)["bracket"]

    assert bracket["closed"] is True
    assert bracket["low"] <= 50.0 <= bracket["high"]
    assert bracket["relative_width"] == pytest.approx(bracket["high"] / bracket["low"] - 1.0)
    assert bracket["relative_width"] <= 0.01


def test_a_minimiser_publishes_no_bracket() -> None:
    optimizer = build_optimizer("random_search", _log_space(), seed=3)
    session = CalibrationEngine(
        space=_log_space(), optimizer=optimizer, evaluator=_root_at(50.0), max_iter=3
    ).run()

    extra = _search_outcome_extra(session)

    assert "bracket" not in extra
    assert extra["search"]["converged"] is True
    assert extra["search"]["stopping_rule"] == BUDGET_RULE


def _report(*, converged: bool | None) -> CalibrationReport:
    extra = {}
    if converged is not None:
        extra["search"] = {
            "converged": converged,
            "stopping_rule": "rel_tol",
            "max_iter": 48,
            "extension": 24,
            "n_evaluations": 72,
        }
    return CalibrationReport(
        session_id="s1",
        method="bisection",
        n_iterations=72,
        best_objective=2.9,
        best_sim_id=None,
        duration_s=1.0,
        save_runs="none",
        promoted=0,
        best_parameters={"K": 2.1e-4},
        extra=extra,
    )


def test_a_phase_that_did_not_converge_is_not_converged() -> None:
    assert not _converged(_report(converged=False))
    assert _converged(_report(converged=True))


def test_a_report_without_a_search_record_is_judged_on_its_candidate() -> None:
    assert _converged(_report(converged=None))


def test_nothing_is_frozen_from_a_phase_that_did_not_converge(caplog) -> None:
    decl = SimpleNamespace(name="steady", freeze_on_success=True, parameters=("K",))
    with caplog.at_level(logging.WARNING):
        froze = _frozen_by(decl, _report(converged=False), _log_space())

    assert froze == ()
    assert "before its stopping rule (rel_tol) was met" in caplog.text


def test_a_phase_built_on_an_unconverged_one_is_refused() -> None:
    decl = SimpleNamespace(name="steady", freeze_on_success=True, parameters=("K",))
    remaining = [SimpleNamespace(decl=SimpleNamespace(name="transient", depends_on="steady"))]

    with pytest.raises(CalibrationError) as caught:
        _require_result_for_dependents(decl, _report(converged=False), remaining)

    message = str(caught.value)
    assert "max_iter = 48, plus 24 granted once" in message
    assert "Raise max_iter or loosen the tolerance" in message
    assert "['transient']" in message


def _session_that(*, converged: bool) -> SimpleNamespace:
    return SimpleNamespace(
        converged=converged,
        stopping_rule="rel_tol",
        history=[None] * 9,
        max_iter=6,
        extension=3,
    )


def test_an_unconverged_search_closes_its_session_as_partial() -> None:
    status, error = _status_of_the_search(_session_that(converged=False), "completed", None)

    assert status == "partial"
    assert error == (
        "stopping rule (rel_tol) not met after 9 evaluations (max_iter = 6, extension = 3)"
    )


def test_a_converged_search_keeps_the_status_its_trials_earned() -> None:
    assert _status_of_the_search(_session_that(converged=True), "completed", None) == (
        "completed",
        None,
    )
    assert _status_of_the_search(_session_that(converged=False), "failed", "boom") == (
        "failed",
        "boom",
    )


# --------------------------------------------------------------------------- #
# The simplex, the other engine that declares a stopping rule
# --------------------------------------------------------------------------- #


def _two_dimensional_space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="K", lower=1.0, upper=1.0e3, transform="log"),
            CalibParameter(name="S", lower=1.0, upper=1.0e3, transform="log"),
        ]
    )


def _rosenbrock(sugg: ParamSuggestion) -> EvaluationResult:
    """A valley the simplex crawls along, far from any tight tolerance in 30 steps."""
    x = math.log10(float(sugg.values["K"]))
    y = math.log10(float(sugg.values["S"]))
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        objective_value=(1.0 - x) ** 2 + 100.0 * (y - x * x) ** 2,
        status="completed",
    )


def _bowl(sugg: ParamSuggestion) -> EvaluationResult:
    x = math.log10(float(sugg.values["K"])) - 1.5
    y = math.log10(float(sugg.values["S"])) - 1.5
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        objective_value=x * x + y * y,
        status="completed",
    )


def test_a_simplex_stopped_by_the_engine_budget_has_not_converged(caplog) -> None:
    space = _two_dimensional_space()
    optimizer = ScipyNelderMead(space, maxiter=1000, maxfev=1000, xatol=1e-12, fatol=1e-14)
    engine = CalibrationEngine(space=space, optimizer=optimizer, evaluator=_rosenbrock, max_iter=20)
    with caplog.at_level(logging.WARNING):
        session = engine.run()

    assert session.stopping_rule == "xatol"
    assert not session.converged
    assert session.extension == 10
    assert len(session.history) == 30
    assert "did NOT converge" in caplog.text


def test_a_simplex_that_meets_its_tolerance_converges() -> None:
    space = _two_dimensional_space()
    optimizer = ScipyNelderMead(space, maxiter=500, maxfev=500)
    engine = CalibrationEngine(space=space, optimizer=optimizer, evaluator=_bowl, max_iter=200)

    session = engine.run()

    assert session.converged
    assert session.extension == 0
    assert len(session.history) < 200


def test_a_simplex_stopped_by_its_own_evaluation_cap_has_not_converged() -> None:
    # SciPy's own maxfev (100 by default) ends the thread with success False:
    # the thread ending is not the simplex meeting its tolerance.
    space = _two_dimensional_space()
    optimizer = ScipyNelderMead(space, xatol=1e-12, fatol=1e-14)
    engine = CalibrationEngine(
        space=space, optimizer=optimizer, evaluator=_rosenbrock, max_iter=200
    )

    session = engine.run()

    assert len(session.history) == 100
    assert not session.converged
