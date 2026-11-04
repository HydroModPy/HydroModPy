"""Tests of `optim.stopping`."""

from __future__ import annotations

import json
import logging
import math
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config import CalibPhaseDecl, MatchingHydrographicNetworkOptions
from hydromodpy.calibration.optim.adapters.bisection_adapter import (
    BisectionAdapter,
    root_search_budget,
)
from hydromodpy.calibration.optim.adapters.scipy_adapter import ScipyNelderMead
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import (
    EngineTraits,
    EvaluationResult,
    ParamSuggestion,
    build_optimizer,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import (
    AUTO_BUDGET,
    UNCOUNTED_BUDGET,
    CountedBudget,
    remaining_grant,
    resolve_budget,
    search_width,
    settled,
    short_budget,
    stop_state,
    stopping_kwargs,
    stopping_rule,
)
from hydromodpy.calibration.preflight import _check_the_budgets
from hydromodpy.calibration.protocols import expand_calibration_protocol
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.cli_runner import (
    _search_outcome_extra,
    load_toml_calibration,
    search_status,
)
from hydromodpy.calibration.runners.staged_runner import (
    _frozen_by,
    _require_result_for_dependents,
    _settled,
)
from hydromodpy.cli.commands.calibrate import _search_line
from hydromodpy.core.exceptions import CalibrationError, OptimizerError
from hydromodpy.results.checks import BUDGET_RULE, CalibratedBy, stop_text
from hydromodpy.results.session.descriptor import SessionDescriptor
from hydromodpy.results.session.phase import PhaseDescriptor
from tests._helpers.session_documents import session_descriptor
from tests.unit.calibration._factories_search import result_of, run_engine

# From test_a_search_says_why_it_stopped.py
# A search says why it stopped, in one of three words, and seals it.
#
# The engine's own rule was met (``rule_met``), every point of its plan was
# solved (``plan_exhausted``), or the budget ended first (``budget_spent``).
# Only the first two are convergence. A search with no rule of its own, a
# random search, spends its budget by design: it did not converge, and its
# session still closes ``completed``, since there was no rule to miss. The
# state is written in the search record, in ``session.json``, in the phase
# descriptor and on the promoted run, and an older file without it still
# reads.


def _space(dim: int = 1) -> ParameterSpace:
    names = ["K", "S"][:dim]
    return ParameterSpace(
        [CalibParameter(name=name, lower=1.0, upper=1.0e3, search_space="log") for name in names]
    )


def _bowl(sugg: ParamSuggestion) -> EvaluationResult:
    cost = sum((math.log10(float(value)) - 1.5) ** 2 for value in sugg.values.values())
    return result_of(sugg, cost)


def _rosenbrock(sugg: ParamSuggestion) -> EvaluationResult:
    x = math.log10(float(sugg.values["K"]))
    y = math.log10(float(sugg.values["S"]))
    return result_of(sugg, (1.0 - x) ** 2 + 100.0 * (y - x * x) ** 2)


def _signed_root(sugg: ParamSuggestion) -> EvaluationResult:
    residual = math.log10(30.0) - math.log10(float(sugg.values["K"]))
    return result_of(sugg, abs(residual), components={"net.J_signed": residual})


def _run(optimizer, evaluator, max_trials, space=None):
    return run_engine(space or optimizer.space, optimizer, evaluator, max_trials)


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


def test_a_rule_engine_that_spent_its_budget_closes_partial() -> None:
    space = _space(2)
    optimizer = ScipyNelderMead(space, maxiter=1000, maxfev=1000, xatol=1e-12, fatol=1e-14)
    session = _run(optimizer, _rosenbrock, 20, space)

    assert search_status(session) == "partial"


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
    return session_descriptor(method="random_search", **extra)


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


# From test_a_search_that_runs_out_of_budget_has_not_converged.py
# A search that stops on its budget before its own rule has not converged.
#
# The root search counts its evaluations before the first solve: its sweep, one
# halving per step down to the tolerance, two evaluations per bracket expansion.
# ``max_trials = "auto"`` budgets the worst case, a declared budget below the
# nominal case is refused, one below the worst case is announced, and a budget
# that still runs out gets exactly the halvings left, once. An engine that cannot
# count gets no extension at all. A search that did not meet its rule says so, the
# report records it, nothing is frozen from the phase, and a phase that depends on
# it is refused.


NANCON_BOUNDS = (1e-7, 1e-3)


def _log_space(lower: float = 1.0, upper: float = 1.0e3) -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="K", lower=lower, upper=upper, search_space="log")])


def _root_at(root: float, calls: list[int] | None = None):
    """A continuous residual, positive below *root* and negative above it."""

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        if calls is not None:
            calls.append(sugg.trial_id)
        residual = math.log10(root) - math.log10(float(sugg.values["K"]))
        return result_of(sugg, abs(residual), components={"net.J_signed": residual})

    return evaluate


def _nancon(**kwargs) -> BisectionAdapter:
    return BisectionAdapter(_log_space(*NANCON_BOUNDS), **kwargs)


def _run__search_that(adapter: BisectionAdapter, root: float, max_trials: int | str):
    return run_engine(adapter.space, adapter, _root_at(root), max_trials)


# --------------------------------------------------------------------------- #
# How much the root search needs, known before the first solve
# --------------------------------------------------------------------------- #
def test_the_nancon_search_needs_fifteen_and_at_worst_twenty_three() -> None:
    budget = root_search_budget(*NANCON_BOUNDS, rel_tol=0.01, sweep_points=7)

    assert budget.counts == (15, 17, 19, 21, 23)
    assert (budget.nominal, budget.worst) == (15, 23)


@pytest.mark.parametrize(
    ("bounds", "options", "counts"),
    [
        # The WRR bounds: a sweep step wider than a decade needs one more halving
        # inside the bounds than after an expansion.
        ((1e-10, 1e-2), {}, (16, 17, 19, 21, 23)),
        ((1e-7, 1e-3), {"rel_tol": 0.001}, (18, 21, 23, 25, 27)),
        ((1e-7, 1e-3), {"sweep_points": 0}, (12, 12, 14, 16, 18)),
        ((1e-7, 1e-3), {"bracket_expand": 0}, (15,)),
        # A sweep finer than the tolerance needs no halving.
        ((1.0, 1.001), {"sweep_points": 3, "bracket_expand": 0}, (3,)),
    ],
)
def test_the_count_follows_the_bounds_sweep_tolerance_and_expansions(
    bounds, options, counts
) -> None:
    assert root_search_budget(*bounds, **options).counts == counts


def test_bounds_that_are_not_a_positive_interval_are_refused() -> None:
    with pytest.raises(ValueError, match="0 < lower < upper"):
        root_search_budget(0.0, 1.0)
    with pytest.raises(ValueError, match="rel_tol"):
        root_search_budget(1.0, 10.0, rel_tol=0.0)


def test_the_adapter_publishes_the_count_of_its_own_options() -> None:
    assert _nancon().counted_budget == root_search_budget(*NANCON_BOUNDS)
    assert _nancon(rel_tol=0.001).counted_budget.counts == (18, 21, 23, 25, 27)


@pytest.mark.parametrize(
    ("root", "expansions", "spent"),
    [
        (2.09e-4, 0, 15),
        (3.3e-6, 0, 15),
        (3e-3, 1, 17),
        (3e-2, 2, 19),
        (3e-1, 3, 21),
        (5e-11, 4, 23),
    ],
)
def test_the_count_is_what_the_search_actually_spends(root, expansions, spent) -> None:
    adapter = _nancon()
    session = _run__search_that(adapter, root, AUTO_BUDGET)

    assert session.converged
    assert session.extension == 0
    assert len(session.history) == adapter.counted_budget.counts[expansions] == spent


def test_the_worst_case_of_a_pure_bisection_is_what_it_spends() -> None:
    adapter = _nancon(sweep_points=0)
    session = _run__search_that(adapter, 5e-11, AUTO_BUDGET)

    assert session.converged
    assert len(session.history) == adapter.counted_budget.worst == 18


# --------------------------------------------------------------------------- #
# "auto", a refusal before the first solve, and a warning
# --------------------------------------------------------------------------- #
def test_auto_budgets_the_worst_case_of_a_counting_engine() -> None:
    adapter = _nancon()

    assert resolve_budget(adapter, AUTO_BUDGET) == 23
    assert _run__search_that(adapter, 2.09e-4, AUTO_BUDGET).max_trials == 23


def test_auto_gives_an_engine_that_cannot_count_its_usual_hundred() -> None:
    optimizer = build_optimizer("random_search", _log_space(), seed=1)

    assert resolve_budget(optimizer, AUTO_BUDGET) == UNCOUNTED_BUDGET == 100
    assert resolve_budget(optimizer, 12) == 12
    with pytest.raises(ValueError, match="auto"):
        resolve_budget(optimizer, "many")


def test_three_expansions_converge_under_auto_without_an_extension(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        session = _run__search_that(_nancon(), 3e-1, AUTO_BUDGET)

    assert session.converged
    assert session.extension == 0
    assert len(session.history) == 21
    assert "Granting" not in caplog.text


def test_a_budget_below_the_nominal_count_is_refused_before_the_first_solve() -> None:
    adapter = _nancon()
    calls: list[int] = []
    engine = CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=_root_at(2.09e-4, calls), max_trials=10
    )

    with pytest.raises(OptimizerError) as caught:
        engine.run()

    assert calls == []
    assert "max_trials = 10 is below the 15 evaluations" in str(caught.value)
    assert '"auto" (23 here' in str(caught.value)


def test_a_budget_below_the_worst_case_is_announced_with_what_it_covers(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        session = _run__search_that(_nancon(), 2.09e-4, 18)

    assert session.converged
    assert "max_trials = 18 covers 1 bracket expansion(s) of the 4" in caplog.text
    assert "the worst case needs 23" in caplog.text


def test_a_budget_that_covers_the_worst_case_says_nothing(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        session = _run__search_that(_nancon(), 2.09e-4, 23)

    assert session.converged
    assert caplog.text == ""


def test_the_verdict_on_a_declared_budget() -> None:
    counted = CountedBudget(counts=(15, 17, 19, 21, 23))

    assert short_budget(counted, 23) is None
    assert short_budget(counted, 40) is None
    assert short_budget(counted, 20)[0] == "warning"
    assert "covers 2 bracket expansion(s)" in short_budget(counted, 20)[1]
    assert short_budget(counted, 15)[0] == "warning"
    assert short_budget(counted, 14)[0] == "error"


# --------------------------------------------------------------------------- #
# At run time: exactly the halvings left, once, or nothing
# --------------------------------------------------------------------------- #
def test_a_budget_two_halvings_short_is_granted_exactly_two(caplog) -> None:
    # One expansion needs 17 evaluations; 15 leaves the bracket two halvings wide.
    with caplog.at_level(logging.WARNING):
        session = _run__search_that(_nancon(), 3e-3, 15)

    assert session.converged
    assert session.max_trials == 15
    assert session.extension == 2
    assert len(session.history) == 17
    assert "needs 2 more to meet its stopping rule (rel_tol). Granting exactly those 2" in (
        caplog.text
    )


def test_the_grant_is_the_count_the_engine_reports_or_nothing() -> None:
    assert remaining_grant(2, 15) == 2
    assert remaining_grant(8, 15) == 8
    assert remaining_grant(9, 15) == 0
    assert remaining_grant(0, 15) == 0
    assert remaining_grant(None, 15) == 0
    assert remaining_grant(True, 15) == 0


def test_the_root_search_reports_the_halvings_its_bracket_still_needs() -> None:
    adapter = _nancon()
    evaluate = _root_at(3e-3)
    assert adapter.evaluations_remaining is None

    # Sweep 7, one expansion 2, then three of the eight halvings.
    for _ in range(12):
        adapter.tell([evaluate(suggestion) for suggestion in adapter.ask(1)])
    assert adapter.evaluations_remaining == 5

    while not adapter.converged():
        adapter.tell([evaluate(suggestion) for suggestion in adapter.ask(1)])
    assert adapter.evaluations_remaining == 0


class _FarFromItsRule:
    """A judged engine that never converges and says it still needs fifty solves."""

    name = "far"
    traits = EngineTraits(precision_option="xatol")
    evaluations_remaining = 50

    def __init__(self) -> None:
        self._trial = 0

    def ask(self, n: int = 1) -> list[ParamSuggestion]:
        self._trial += 1
        return [ParamSuggestion(trial_id=self._trial, values={"K": 10.0})]

    def tell(self, results) -> None:
        del results

    def best(self):
        return None

    def converged(self) -> bool:
        return False


def test_a_need_beyond_half_the_budget_is_not_granted(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        session = run_engine(_log_space(), _FarFromItsRule(), _root_at(50.0), 10)

    assert not session.converged
    assert session.extension == 0
    assert len(session.history) == 10
    assert "still needs 50" in caplog.text
    assert "nothing is granted" in caplog.text


def test_an_engine_with_a_rule_names_it_and_a_budget_engine_does_not() -> None:
    assert stopping_rule(_nancon()) == "rel_tol"
    assert stopping_rule(build_optimizer("random_search", _log_space(), seed=1)) == BUDGET_RULE


def test_a_budget_engine_spends_its_budget_and_settles_unconverged(caplog) -> None:
    optimizer = build_optimizer("random_search", _log_space(), seed=3)
    engine = CalibrationEngine(
        space=_log_space(), optimizer=optimizer, evaluator=_root_at(50.0), max_trials=4
    )
    with caplog.at_level(logging.WARNING):
        session = engine.run()

    assert session.stop_state == "budget_spent"
    assert not session.converged
    assert session.settled
    assert session.extension == 0
    assert len(session.history) == 4
    assert "Granting" not in caplog.text
    assert "the best of a budget-only search" in caplog.text


# --------------------------------------------------------------------------- #
# Where the budget is declared, and checked
# --------------------------------------------------------------------------- #
def test_the_protocol_writes_auto_for_its_steady_stage() -> None:
    doc = {
        "simulation": {
            "time": {
                "start_datetime": "1995-01-01",
                "end_datetime": "2020-12-31",
                "step_value": 1,
                "step_unit": "day",
            }
        },
        "data": {"hydrometry": {"sources": [{"station_ids": ["NANCON"]}]}},
        "calibration": {
            "protocol": "matching_hydrographic_network",
            "parameters": {
                "K": {"bounds": list(NANCON_BOUNDS), "search_space": "log"},
                "Sy": {"bounds": [1e-4, 0.5], "search_space": "log"},
            },
            "outputs": {"seepage_network": {"support": "network", "map": {"complete": "n.gpkg"}}},
        },
    }

    steady, transient = expand_calibration_protocol(doc)["calibration"]["phases"]

    assert (steady["method"], steady["max_trials"]) == ("bisection", AUTO_BUDGET)
    assert transient["max_trials"] == 120


def test_the_budget_fields_take_auto_or_a_positive_integer() -> None:
    assert MatchingHydrographicNetworkOptions(
        name="matching_hydrographic_network"
    ).steady_max_trials
    assert CalibPhaseDecl(name="p", parameters=["K"]).max_trials is None
    assert CalibPhaseDecl(name="p", parameters=["K"], max_trials="auto").max_trials == AUTO_BUDGET
    assert CalibPhaseDecl(name="p", parameters=["K"], max_trials=12).max_trials == 12
    with pytest.raises(ValueError):
        CalibPhaseDecl(name="p", parameters=["K"], max_trials=0)
    with pytest.raises(ValueError):
        CalibPhaseDecl(name="p", parameters=["K"], max_trials="many")


_HEAD = """
[workspace]
name = "budget_probe"

[simulation.time]
start_datetime = "2000-01-01"
end_datetime = "2000-12-31"
step_value = 1
step_unit = "day"

[[data.hydrometry.sources]]
station_ids = ["G1"]

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
units = "m/s"

[calibration.parameters.Sy]
bounds = [1e-4, 0.5]
search_space = "log"
units = "-"

[calibration.outputs.seepage_network]
support = "network"
map.complete = "network.gpkg"
"""


def _budget_findings(tmp_path: Path, **protocol):
    """Check the budgets of the matching protocol; ``protocol`` sets its keys as TOML values."""
    lines = "".join(f"{key} = {json.dumps(value)}\n" for key, value in protocol.items())
    path = tmp_path / "budget.toml"
    path.write_text(
        textwrap.dedent(_HEAD)
        + '[calibration.protocol]\nname = "matching_hydrographic_network"\n'
        + lines,
        encoding="utf-8",
    )
    (tmp_path / "network.gpkg").write_bytes(b"")
    cfg, _raw = load_toml_calibration(path)
    return _check_the_budgets(cfg)


def test_the_preflight_refuses_a_steady_budget_below_fifteen(tmp_path: Path) -> None:
    findings = _budget_findings(tmp_path, steady_max_trials=10)

    assert [finding.severity for finding in findings] == ["error"]
    assert findings[0].where == "[[calibration.phases]] 'steady_conductivity'"
    assert "max_trials = 10 is below the 15 evaluations" in findings[0].detail
    assert "steady_max_trials" in findings[0].detail


def test_the_preflight_announces_a_steady_budget_below_the_worst_case(tmp_path: Path) -> None:
    findings = _budget_findings(tmp_path, steady_max_trials=18)

    assert [finding.severity for finding in findings] == ["warning"]
    assert "covers 1 bracket expansion(s) of the 4" in findings[0].detail


def test_the_preflight_reads_the_stage_options_into_the_count(tmp_path: Path) -> None:
    # At 0.1 % the nominal count is 18, so 16 no longer passes.
    findings = _budget_findings(tmp_path, steady_max_trials=16, steady_precision=0.001)

    assert [finding.severity for finding in findings] == ["error"]
    assert "below the 18 evaluations" in findings[0].detail


@pytest.mark.parametrize("budget", ["auto", 23, 40])
def test_the_preflight_passes_auto_and_a_budget_that_covers_the_worst_case(
    tmp_path: Path, budget
) -> None:
    assert _budget_findings(tmp_path, steady_max_trials=budget) == []


def test_the_preflight_leaves_an_engine_that_cannot_count_alone(tmp_path: Path) -> None:
    findings = _budget_findings(
        tmp_path,
        steady_method="scipy_nelder_mead",
        steady_metric="distance_mean",
        steady_max_trials=3,
        transient_max_trials=2,
    )

    assert findings == []


# --------------------------------------------------------------------------- #
# What the report and the staged runner do with it
# --------------------------------------------------------------------------- #
def test_the_report_records_the_verdict_and_the_open_bracket() -> None:
    adapter = _nancon()
    session = run_engine(adapter.space, adapter, _root_at(5e-11), 16)

    extra = _search_outcome_extra(session)

    # Four expansions leave the bracket eight halvings wide at 16 evaluations,
    # and eight is exactly half the budget: granted, and closed.
    assert extra["search"] == {
        "stop_state": "rule_met",
        "converged": True,
        "stopping_rule": "rel_tol",
        "max_trials": 16,
        "extension": 7,
        "n_evaluations": 23,
    }
    assert extra["bracket"]["closed"] is True


def test_the_report_publishes_an_open_bracket_when_nothing_was_granted(caplog) -> None:
    # A pure bisection on [1, 1.5] at 0.01 %: 14 evaluations inside the bounds.
    # A root three decades out spends 8 on the bounds and the expansions, 6 on
    # halvings, and still needs 9, more than half of 14.
    adapter = BisectionAdapter(_log_space(1.0, 1.5), sweep_points=0, rel_tol=0.0001)
    assert adapter.counted_budget.nominal == 14
    with caplog.at_level(logging.WARNING):
        session = run_engine(adapter.space, adapter, _root_at(4e-3), 14)

    extra = _search_outcome_extra(session)

    assert extra["search"] == {
        "stop_state": "budget_spent",
        "converged": False,
        "stopping_rule": "rel_tol",
        "max_trials": 14,
        "extension": 0,
        "n_evaluations": 14,
    }
    assert "still needs 9" in caplog.text
    bracket = extra["bracket"]
    assert bracket["parameter"] == "K"
    assert bracket["closed"] is False
    assert bracket["low"] < 4e-3 < bracket["high"]
    assert bracket["relative_width"] > 0.0001


def test_the_report_publishes_the_closed_bracket_in_physical_units() -> None:
    adapter = _nancon()
    session = _run__search_that(adapter, 2.09e-4, AUTO_BUDGET)

    bracket = _search_outcome_extra(session)["bracket"]

    assert bracket["closed"] is True
    assert bracket["low"] <= 2.09e-4 <= bracket["high"]
    assert bracket["relative_width"] == pytest.approx(bracket["high"] / bracket["low"] - 1.0)
    assert bracket["relative_width"] <= 0.01


def test_a_minimiser_publishes_no_bracket() -> None:
    optimizer = build_optimizer("random_search", _log_space(), seed=3)
    session = run_engine(_log_space(), optimizer, _root_at(50.0), 3)

    extra = _search_outcome_extra(session)

    assert "bracket" not in extra
    assert extra["search"]["converged"] is False
    assert extra["search"]["stop_state"] == "budget_spent"
    assert extra["search"]["stopping_rule"] == BUDGET_RULE


def _report(*, converged: bool | None) -> CalibrationReport:
    extra = {}
    if converged is not None:
        extra["search"] = {
            "stop_state": "rule_met" if converged else "budget_spent",
            "converged": converged,
            "stopping_rule": "xatol",
            "max_trials": 120,
            "extension": 0,
            "n_evaluations": 120,
        }
    return CalibrationReport(
        session_id="s1",
        method="scipy_nelder_mead",
        n_trials=120,
        best_cost=2.9,
        duration_s=1.0,
        save_runs="none",
        promoted=0,
        best_parameters={"K": 2.1e-4},
        extra=extra,
    )


def test_a_phase_that_did_not_converge_is_not_settled() -> None:
    assert not _settled(_report(converged=False))
    assert _settled(_report(converged=True))


def test_a_report_without_a_search_record_is_judged_on_its_candidate() -> None:
    assert _settled(_report(converged=None))


def test_nothing_is_frozen_from_a_phase_that_did_not_converge(caplog) -> None:
    decl = SimpleNamespace(name="steady", freeze_on_success=True, parameters=("K",))
    with caplog.at_level(logging.WARNING):
        froze = _frozen_by(decl, _report(converged=False), _log_space())

    assert froze == ()
    assert "before its stopping rule (xatol) was met" in caplog.text


def test_a_phase_built_on_an_unconverged_one_is_refused() -> None:
    decl = SimpleNamespace(name="steady", freeze_on_success=True, parameters=("K",))
    remaining = [SimpleNamespace(decl=SimpleNamespace(name="transient", depends_on="steady"))]

    with pytest.raises(CalibrationError) as caught:
        _require_result_for_dependents(decl, _report(converged=False), remaining)

    message = str(caught.value)
    assert "max_trials = 120, plus 0 granted once" in message
    assert "Raise max_trials: a re-run of the same file replays" in message
    assert "['transient']" in message


# --------------------------------------------------------------------------- #
# The simplex, an engine with a rule it cannot count
# --------------------------------------------------------------------------- #
def _two_dimensional_space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="K", lower=1.0, upper=1.0e3, search_space="log"),
            CalibParameter(name="S", lower=1.0, upper=1.0e3, search_space="log"),
        ]
    )


def _rosenbrock__search_that(sugg: ParamSuggestion) -> EvaluationResult:
    """A valley the simplex crawls along, far from any tight tolerance in 20 steps."""
    x = math.log10(float(sugg.values["K"]))
    y = math.log10(float(sugg.values["S"]))
    return result_of(sugg, (1.0 - x) ** 2 + 100.0 * (y - x * x) ** 2)


def _bowl__search_that(sugg: ParamSuggestion) -> EvaluationResult:
    x = math.log10(float(sugg.values["K"])) - 1.5
    y = math.log10(float(sugg.values["S"])) - 1.5
    return result_of(sugg, x * x + y * y)


def test_a_simplex_that_spends_its_budget_gets_no_extension(caplog) -> None:
    space = _two_dimensional_space()
    optimizer = ScipyNelderMead(space, maxiter=1000, maxfev=1000, xatol=1e-12, fatol=1e-14)
    engine = CalibrationEngine(
        space=space, optimizer=optimizer, evaluator=_rosenbrock__search_that, max_trials=20
    )
    with caplog.at_level(logging.WARNING):
        session = engine.run()

    assert session.stopping_rule == "xatol"
    assert not session.converged
    assert session.extension == 0
    assert len(session.history) == 20
    assert "Granting" not in caplog.text
    assert "did NOT converge" in caplog.text


def test_a_simplex_that_meets_its_tolerance_converges() -> None:
    space = _two_dimensional_space()
    optimizer = ScipyNelderMead(space, maxiter=500, maxfev=500)
    session = run_engine(space, optimizer, _bowl__search_that, 200)

    assert session.converged
    assert session.extension == 0
    assert len(session.history) < 200


def test_a_simplex_stopped_by_its_own_evaluation_cap_has_not_converged() -> None:
    # SciPy's own maxfev, written in the options, ends the thread with success
    # False: the thread ending is not the simplex meeting its tolerance.
    space = _two_dimensional_space()
    optimizer = ScipyNelderMead(space, xatol=1e-12, fatol=1e-14, maxfev=100)
    session = run_engine(space, optimizer, _rosenbrock__search_that, 200)

    assert len(session.history) == 100
    assert not session.converged


# From test_an_auto_budget_covers_the_whole_grid.py
# ``max_trials = "auto"`` sizes a grid to every one of its points.
#
# The grid published no counted budget, so ``"auto"`` gave it the budget of an
# engine that cannot count, 100: three parameters on five points each, 125
# points, were cut at 100, the last value of the first parameter never visited,
# and the session still reported a converged search.


def _space__auto_budget() -> ParameterSpace:
    return ParameterSpace(
        [CalibParameter(name=name, lower=0.0, upper=1.0) for name in ("a", "b", "c")]
    )


def _evaluate(suggestion):
    return result_of(
        suggestion,
        float(sum(suggestion.values.values())),
        metadata={"values": dict(suggestion.values)},
    )


def test_auto_budgets_every_point_of_the_grid() -> None:
    optimizer = build_optimizer("grid", _space__auto_budget(), points_per_dim=5)

    assert resolve_budget(optimizer, "auto") == 125


def test_the_whole_grid_is_visited() -> None:
    space = _space__auto_budget()
    optimizer = build_optimizer("grid", space, points_per_dim=[5, 5, 6])
    session = run_engine(space, optimizer, _evaluate, "auto")

    assert len(session.history) == 150
    assert max(result.metadata["values"]["a"] for result in session.history) == 1.0


# From test_one_precision_for_every_engine.py
# A file says how precisely it wants the answer, not what scipy calls it.
#
# Nine engines stop for nine reasons and name the rule nine ways. The precision is
# stated once, on the parameter, and each engine's traits say which of its own
# options that writes. What is gated here is the arithmetic of that translation,
# because a wrong conversion does not fail: it reports convergence on a bracket
# orders of magnitude wide.


K = CalibParameter(name="K", lower=1e-8, upper=1e-2, search_space="log")
SY = CalibParameter(name="Sy", lower=1e-4, upper=0.5, search_space="log")
POROSITY = CalibParameter(name="n", lower=0.0, upper=0.4, search_space="identity")


def test_a_log_parameter_reads_a_precision_as_a_ratio() -> None:
    # Ten per cent on a conductivity is 0.0414 decades wherever the value sits,
    # so the bounds do not enter at all.
    assert search_width(K, 0.10) == pytest.approx(math.log10(1.1))
    assert search_width(SY, 0.10) == pytest.approx(math.log10(1.1))


def test_a_linear_parameter_reads_it_as_a_fraction_of_its_interval() -> None:
    # Nothing on the value to be relative to before the search has a value.
    assert search_width(POROSITY, 0.05) == pytest.approx(0.05 * 0.4)


def test_nelder_mead_gets_the_precision_as_an_absolute_width() -> None:
    kwargs = stopping_kwargs("scipy_nelder_mead", ParameterSpace([K]), precision=0.10)
    assert kwargs == {"xatol": pytest.approx(math.log10(1.1))}


def test_the_strictest_parameter_sets_the_width() -> None:
    # One number stops the search for every parameter at once.
    space = ParameterSpace([K, POROSITY])
    kwargs = stopping_kwargs("scipy_nelder_mead", space, precision=0.05)
    assert kwargs["xatol"] == pytest.approx(
        min(search_width(K, 0.05), search_width(POROSITY, 0.05))
    )


def test_the_root_search_reads_the_same_number_unconverted() -> None:
    # rel_tol is already a relative width on the parameter's own value, and the
    # paper's one per cent is the engine's default, so the two agree.
    kwargs = stopping_kwargs("bisection", ParameterSpace([K]), precision=0.01)
    assert kwargs == {"rel_tol": 0.01}


def test_the_declared_kwargs_pass_through_untouched_without_a_precision() -> None:
    declared = {"maxiter": 30, "xatol": 0.30}
    assert (
        stopping_kwargs("scipy_nelder_mead", ParameterSpace([K]), precision=None, declared=declared)
        == declared
    )


def test_the_precision_joins_the_other_declared_kwargs() -> None:
    kwargs = stopping_kwargs(
        "scipy_nelder_mead", ParameterSpace([K]), precision=0.10, declared={"maxiter": 30}
    )
    assert kwargs["maxiter"] == 30
    assert kwargs["xatol"] == pytest.approx(math.log10(1.1))


def test_saying_it_twice_is_refused() -> None:
    with pytest.raises(ValueError, match="both set the"):
        stopping_kwargs(
            "scipy_nelder_mead", ParameterSpace([K]), precision=0.10, declared={"xatol": 0.30}
        )


def test_an_engine_that_stops_on_its_budget_refuses_a_precision() -> None:
    # Silently dropping it would report a search that honored a request it never
    # read. The message has to name what does bound that engine.
    with pytest.raises(ValueError, match="max_trials"):
        stopping_kwargs("grid", ParameterSpace([K]), precision=0.10)


def test_the_built_optimizers_accept_what_the_translation_produces() -> None:
    space = ParameterSpace([K])
    for method, extra in (("scipy_nelder_mead", {}), ("bisection", {"sweep_points": 0})):
        kwargs = stopping_kwargs(method, space, precision=0.05, declared=extra)
        assert build_optimizer(method, space, **kwargs) is not None
