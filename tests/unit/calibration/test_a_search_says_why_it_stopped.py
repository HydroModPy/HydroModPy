"""A search says why it stopped, in one of three words, and seals it.

The engine's own rule was met (``rule_met``), every point of its plan was
solved (``plan_exhausted``), or the budget ended first (``budget_spent``).
Only the first two are convergence. A search with no rule of its own, a
random search, spends its budget by design: it did not converge, and its
session still closes ``completed``, since there was no rule to miss. The
state is written in the search record, in ``session.json``, in the phase
descriptor and on the promoted run, and an older file without it still
reads.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.adapters.bisection_adapter import BisectionAdapter
from hydromodpy.calibration.optim.adapters.scipy_adapter import ScipyNelderMead
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import (
    EngineTraits,
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import CountedBudget, settled, stop_state
from hydromodpy.calibration.runners.cli_runner import (
    _search_outcome_extra,
    _status_of_the_search,
    search_status,
)
from hydromodpy.cli.commands.calibrate import _search_line
from hydromodpy.results.checks import BUDGET_RULE, CalibratedBy, stop_text
from hydromodpy.results.session.descriptor import SessionDescriptor
from hydromodpy.results.session.phase import PhaseDescriptor


def _space(dim: int = 1) -> ParameterSpace:
    names = ["K", "S"][:dim]
    return ParameterSpace(
        [CalibParameter(name=name, lower=1.0, upper=1.0e3, search_space="log") for name in names]
    )


def _bowl(sugg: ParamSuggestion) -> EvaluationResult:
    cost = sum((math.log10(float(value)) - 1.5) ** 2 for value in sugg.values.values())
    return EvaluationResult(
        trial_id=sugg.trial_id, sim_id=None, objective_value=cost, status="completed"
    )


def _rosenbrock(sugg: ParamSuggestion) -> EvaluationResult:
    x = math.log10(float(sugg.values["K"]))
    y = math.log10(float(sugg.values["S"]))
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        objective_value=(1.0 - x) ** 2 + 100.0 * (y - x * x) ** 2,
        status="completed",
    )


def _signed_root(sugg: ParamSuggestion) -> EvaluationResult:
    residual = math.log10(30.0) - math.log10(float(sugg.values["K"]))
    return EvaluationResult(
        trial_id=sugg.trial_id,
        sim_id=None,
        objective_value=abs(residual),
        status="completed",
        components={"net.J_signed": residual},
    )


def _run(optimizer, evaluator, max_trials, space=None):
    return CalibrationEngine(
        space=space or optimizer.space,
        optimizer=optimizer,
        evaluator=evaluator,
        max_trials=max_trials,
    ).run()


# --------------------------------------------------------------------------- #
# The engine names the state
# --------------------------------------------------------------------------- #


def test_a_grid_solved_to_its_last_point_exhausted_its_plan() -> None:
    session = _run(build_optimizer("grid", _space(), points_per_dim=4), _bowl, 4)

    assert session.stop_state == "plan_exhausted"
    assert session.converged
    assert session.settled


def test_a_latin_hypercube_solved_to_its_last_point_exhausted_its_plan() -> None:
    session = _run(build_optimizer("lhs", _space(2), n_samples=6, seed=1), _bowl, 6)

    assert session.stop_state == "plan_exhausted"
    assert session.converged


def test_a_root_search_that_closes_its_bracket_met_its_rule() -> None:
    adapter = BisectionAdapter(_space(), rel_tol=0.01)
    session = _run(adapter, _signed_root, "auto")

    assert session.stop_state == "rule_met"
    assert session.converged


def test_a_simplex_cut_by_the_budget_spent_it() -> None:
    space = _space(2)
    optimizer = ScipyNelderMead(space, maxiter=1000, maxfev=1000, xatol=1e-12, fatol=1e-14)
    session = _run(optimizer, _rosenbrock, 20, space)

    assert session.stop_state == "budget_spent"
    assert not session.converged
    assert not session.settled


def test_a_random_search_spends_its_budget_and_has_not_converged() -> None:
    session = _run(build_optimizer("random_search", _space(), seed=3), _bowl, 4)

    assert session.stopping_rule == BUDGET_RULE
    assert session.stop_state == "budget_spent"
    assert not session.converged
    assert session.settled


class _CutDesign:
    """A design engine whose plan the budget cut short, past the up-front refusal."""

    name = "cut"
    traits = EngineTraits()
    counted_budget = CountedBudget(counts=(25,), step="grid point")


def test_a_design_cut_short_spent_its_budget() -> None:
    assert stop_state(_CutDesign(), met=False, spent=True) == "budget_spent"
    assert stop_state(_CutDesign(), met=True, spent=True) == "plan_exhausted"


def test_a_budget_engine_that_stops_on_a_rule_of_its_options_met_it() -> None:
    budget_only = SimpleNamespace(traits=EngineTraits())

    assert stop_state(budget_only, met=True, spent=False) == "rule_met"
    assert stop_state(budget_only, met=True, spent=True) == "budget_spent"
    assert stop_state(budget_only, met=False, spent=True) == "budget_spent"


def test_only_a_rule_engine_that_spent_its_budget_is_unsettled() -> None:
    assert settled("rule_met", "xatol")
    assert settled("plan_exhausted", "every grid point")
    assert settled("budget_spent", BUDGET_RULE)
    assert not settled("budget_spent", "xatol")
    assert not settled("budget_spent", "every grid point")


# --------------------------------------------------------------------------- #
# The search record and the session status
# --------------------------------------------------------------------------- #


def test_the_search_record_carries_the_state() -> None:
    session = _run(build_optimizer("random_search", _space(), seed=3), _bowl, 3)

    search = _search_outcome_extra(session)["search"]

    assert search["stop_state"] == "budget_spent"
    assert search["converged"] is False
    assert search["stopping_rule"] == BUDGET_RULE


def test_a_random_search_closes_its_session_completed() -> None:
    session = _run(build_optimizer("random_search", _space(), seed=3), _bowl, 3)

    assert search_status(session) == "completed"
    assert _status_of_the_search(session, "completed", None) == ("completed", None)


def test_a_rule_engine_that_spent_its_budget_closes_partial() -> None:
    space = _space(2)
    optimizer = ScipyNelderMead(space, maxiter=1000, maxfev=1000, xatol=1e-12, fatol=1e-14)
    session = _run(optimizer, _rosenbrock, 20, space)

    assert search_status(session) == "partial"
    assert _status_of_the_search(session, "completed", None)[0] == "partial"


# --------------------------------------------------------------------------- #
# The words the console prints
# --------------------------------------------------------------------------- #


def test_the_three_states_read_plainly() -> None:
    assert stop_text("rule_met", "rel_tol") == "met its own rule (rel_tol)"
    assert stop_text("plan_exhausted", "every grid point") == (
        "exhausted its plan (every grid point solved)"
    )
    assert stop_text("budget_spent", BUDGET_RULE) == (
        "spent its budget, a budget-only search with no rule of its own"
    )
    assert stop_text("budget_spent", "xatol") == "spent its budget before its rule (xatol) was met"
    assert stop_text(None, None) == "not recorded"


def test_the_console_says_why_the_search_stopped() -> None:
    line = _search_line(
        {
            "converged": False,
            "stop_state": "budget_spent",
            "stopping_rule": BUDGET_RULE,
            "max_trials": 20,
            "extension": 0,
            "n_evaluations": 20,
        }
    )

    assert line == (
        "search: spent its budget, a budget-only search with no rule of its own, "
        "not converged, 20 evaluation(s) of 20 declared"
    )


# --------------------------------------------------------------------------- #
# Sealed, and an older file still reads
# --------------------------------------------------------------------------- #


def _descriptor(**extra) -> SessionDescriptor:
    return SessionDescriptor(
        session_id="s1",
        case_id="case",
        config_hash="h",
        hydromodpy_version="2.0.0a4",
        method="random_search",
        objective_name="nse",
        started_at=datetime(2026, 10, 25, tzinfo=UTC),
        **extra,
    )


def test_the_session_descriptor_holds_the_state_and_reads_without_it() -> None:
    older = _descriptor()
    assert older.stop_state is None and older.stopping_rule is None

    sealed = _descriptor(stop_state="budget_spent", stopping_rule=BUDGET_RULE)
    payload = sealed.model_dump(mode="json", by_alias=True)

    assert payload["stop_state"] == "budget_spent"
    assert SessionDescriptor.model_validate(payload).stop_state == "budget_spent"
    with pytest.raises(ValueError):
        _descriptor(stop_state="converged")


def test_the_phase_descriptor_holds_the_state_and_reads_without_it() -> None:
    older = PhaseDescriptor(phase_id="p", name="coarse", index=0)
    assert older.stop_state is None

    sealed = PhaseDescriptor(
        phase_id="p", name="coarse", index=0, stop_state="rule_met", stopping_rule="rel_tol"
    )
    assert sealed.model_dump(mode="json", by_alias=True)["stop_state"] == "rule_met"


def test_the_promoted_run_carries_the_state_and_reads_without_it() -> None:
    older = CalibratedBy(session_id="s1", trial=3, session_status="completed")
    assert older.stop_state is None

    sealed = CalibratedBy(
        session_id="s1",
        trial=3,
        session_status="completed",
        stop_state="budget_spent",
        stopping_rule=BUDGET_RULE,
    )
    assert CalibratedBy.model_validate(sealed.model_dump(mode="json")).stop_state == (
        "budget_spent"
    )
