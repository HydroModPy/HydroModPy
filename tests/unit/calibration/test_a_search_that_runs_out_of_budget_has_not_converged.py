"""A search that stops on its budget before its own rule has not converged.

The root search counts its evaluations before the first solve: its sweep, one
halving per step down to the tolerance, two evaluations per bracket expansion.
``max_iter = "auto"`` budgets the worst case, a declared budget below the
nominal case is refused, one below the worst case is announced, and a budget
that still runs out gets exactly the halvings left, once. An engine that cannot
count gets no extension at all. A search that did not meet its rule says so, the
report records it, nothing is frozen from the phase, and a phase that depends on
it is refused.
"""

from __future__ import annotations

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
    BUDGET_RULE,
    UNCOUNTED_BUDGET,
    CountedBudget,
    remaining_grant,
    resolve_budget,
    short_budget,
    stopping_rule,
)
from hydromodpy.calibration.preflight import _check_the_budgets
from hydromodpy.calibration.protocols import expand_calibration_protocol
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.cli_runner import (
    _search_outcome_extra,
    _status_of_the_search,
    load_toml_calibration,
)
from hydromodpy.calibration.runners.staged_runner import (
    _converged,
    _frozen_by,
    _require_result_for_dependents,
)
from hydromodpy.core.exceptions import CalibrationError, OptimizerError

NANCON_BOUNDS = (1e-7, 1e-3)


def _log_space(lower: float = 1.0, upper: float = 1.0e3) -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="K", lower=lower, upper=upper, transform="log")])


def _root_at(root: float, calls: list[int] | None = None):
    """A continuous residual, positive below *root* and negative above it."""

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        if calls is not None:
            calls.append(sugg.trial_id)
        residual = math.log10(root) - math.log10(float(sugg.values["K"]))
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=abs(residual),
            status="completed",
            components={"net.J_signed": residual},
        )

    return evaluate


def _nancon(**kwargs) -> BisectionAdapter:
    return BisectionAdapter(_log_space(*NANCON_BOUNDS), **kwargs)


def _run(adapter: BisectionAdapter, root: float, max_iter: int | str):
    return CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=_root_at(root), max_iter=max_iter
    ).run()


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
    session = _run(adapter, root, AUTO_BUDGET)

    assert session.converged
    assert session.extension == 0
    assert len(session.history) == adapter.counted_budget.counts[expansions] == spent


def test_the_worst_case_of_a_pure_bisection_is_what_it_spends() -> None:
    adapter = _nancon(sweep_points=0)
    session = _run(adapter, 5e-11, AUTO_BUDGET)

    assert session.converged
    assert len(session.history) == adapter.counted_budget.worst == 18


# --------------------------------------------------------------------------- #
# "auto", a refusal before the first solve, and a warning
# --------------------------------------------------------------------------- #


def test_auto_budgets_the_worst_case_of_a_counting_engine() -> None:
    adapter = _nancon()

    assert resolve_budget(adapter, AUTO_BUDGET) == 23
    assert _run(adapter, 2.09e-4, AUTO_BUDGET).max_iter == 23


def test_auto_gives_an_engine_that_cannot_count_its_usual_hundred() -> None:
    optimizer = build_optimizer("random_search", _log_space(), seed=1)

    assert resolve_budget(optimizer, AUTO_BUDGET) == UNCOUNTED_BUDGET == 100
    assert resolve_budget(optimizer, 12) == 12
    with pytest.raises(ValueError, match="auto"):
        resolve_budget(optimizer, "many")


def test_three_expansions_converge_under_auto_without_an_extension(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        session = _run(_nancon(), 3e-1, AUTO_BUDGET)

    assert session.converged
    assert session.extension == 0
    assert len(session.history) == 21
    assert "Granting" not in caplog.text


def test_a_budget_below_the_nominal_count_is_refused_before_the_first_solve() -> None:
    adapter = _nancon()
    calls: list[int] = []
    engine = CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=_root_at(2.09e-4, calls), max_iter=10
    )

    with pytest.raises(OptimizerError) as caught:
        engine.run()

    assert calls == []
    assert "max_iter = 10 is below the 15 evaluations" in str(caught.value)
    assert '"auto" (23 here' in str(caught.value)


def test_a_budget_below_the_worst_case_is_announced_with_what_it_covers(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        session = _run(_nancon(), 2.09e-4, 18)

    assert session.converged
    assert "max_iter = 18 covers 1 bracket expansion(s) of the 4" in caplog.text
    assert "the worst case needs 23" in caplog.text


def test_a_budget_that_covers_the_worst_case_says_nothing(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        session = _run(_nancon(), 2.09e-4, 23)

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
        session = _run(_nancon(), 3e-3, 15)

    assert session.converged
    assert session.max_iter == 15
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
    traits = EngineTraits(tolerance_option="xatol")
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
        session = CalibrationEngine(
            space=_log_space(), optimizer=_FarFromItsRule(), evaluator=_root_at(50.0), max_iter=10
        ).run()

    assert not session.converged
    assert session.extension == 0
    assert len(session.history) == 10
    assert "still needs 50" in caplog.text
    assert "nothing is granted" in caplog.text


def test_an_engine_with_a_rule_names_it_and_a_budget_engine_does_not() -> None:
    assert stopping_rule(_nancon()) == "rel_tol"
    assert stopping_rule(build_optimizer("random_search", _log_space(), seed=1)) == BUDGET_RULE


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
                "K": {"bounds": list(NANCON_BOUNDS), "transform": "log"},
                "Sy": {"bounds": [1e-4, 0.5], "transform": "log"},
            },
            "outputs": {
                "seepage_network": {"support": "network", "stream_geometry_path": "n.gpkg"}
            },
        },
    }

    steady, transient = expand_calibration_protocol(doc)["calibration"]["phases"]

    assert (steady["method"], steady["max_iter"]) == ("bisection", AUTO_BUDGET)
    assert transient["max_iter"] == 120


def test_the_budget_fields_take_auto_or_a_positive_integer() -> None:
    assert MatchingHydrographicNetworkOptions(name="matching_hydrographic_network").steady_max_iter
    assert CalibPhaseDecl(name="p", parameters=["K"]).max_iter == AUTO_BUDGET
    assert CalibPhaseDecl(name="p", parameters=["K"], max_iter=12).max_iter == 12
    with pytest.raises(ValueError):
        CalibPhaseDecl(name="p", parameters=["K"], max_iter=0)
    with pytest.raises(ValueError):
        CalibPhaseDecl(name="p", parameters=["K"], max_iter="many")


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
transform = "log"
units = "m/s"

[calibration.parameters.Sy]
bounds = [1e-4, 0.5]
transform = "log"
units = "-"

[calibration.outputs.seepage_network]
support = "network"
stream_geometry_path = "network.gpkg"
"""


def _budget_findings(tmp_path: Path, protocol: str):
    path = tmp_path / "budget.toml"
    path.write_text(textwrap.dedent(_HEAD) + textwrap.dedent(protocol), encoding="utf-8")
    (tmp_path / "network.gpkg").write_bytes(b"")
    cfg, _raw = load_toml_calibration(path)
    return _check_the_budgets(cfg)


def test_the_preflight_refuses_a_steady_budget_below_fifteen(tmp_path: Path) -> None:
    findings = _budget_findings(
        tmp_path,
        """
        [calibration.protocol]
        name = "matching_hydrographic_network"
        steady_max_iter = 10
        """,
    )

    assert [finding.severity for finding in findings] == ["error"]
    assert findings[0].where == "[[calibration.phases]] 'steady_conductivity'"
    assert "max_iter = 10 is below the 15 evaluations" in findings[0].detail
    assert "steady_max_iter" in findings[0].detail


def test_the_preflight_announces_a_steady_budget_below_the_worst_case(tmp_path: Path) -> None:
    findings = _budget_findings(
        tmp_path,
        """
        [calibration.protocol]
        name = "matching_hydrographic_network"
        steady_max_iter = 18
        """,
    )

    assert [finding.severity for finding in findings] == ["warning"]
    assert "covers 1 bracket expansion(s) of the 4" in findings[0].detail


def test_the_preflight_reads_the_stage_options_into_the_count(tmp_path: Path) -> None:
    # At 0.1 % the nominal count is 18, so 16 no longer passes.
    findings = _budget_findings(
        tmp_path,
        """
        [calibration.protocol]
        name = "matching_hydrographic_network"
        steady_max_iter = 16
        steady_tolerance = 0.001
        """,
    )

    assert [finding.severity for finding in findings] == ["error"]
    assert "below the 18 evaluations" in findings[0].detail


@pytest.mark.parametrize("budget", ['"auto"', "23", "40"])
def test_the_preflight_passes_auto_and_a_budget_that_covers_the_worst_case(
    tmp_path: Path, budget: str
) -> None:
    findings = _budget_findings(
        tmp_path,
        f"""
        [calibration.protocol]
        name = "matching_hydrographic_network"
        steady_max_iter = {budget}
        """,
    )

    assert findings == []


def test_the_preflight_leaves_an_engine_that_cannot_count_alone(tmp_path: Path) -> None:
    findings = _budget_findings(
        tmp_path,
        """
        [calibration.protocol]
        name = "matching_hydrographic_network"
        steady_method = "scipy_nelder_mead"
        steady_metric = "distance_mean"
        steady_max_iter = 3
        transient_max_iter = 2
        """,
    )

    assert findings == []


# --------------------------------------------------------------------------- #
# What the report and the staged runner do with it
# --------------------------------------------------------------------------- #


def test_the_report_records_the_verdict_and_the_open_bracket() -> None:
    adapter = _nancon()
    session = CalibrationEngine(
        space=adapter.space,
        optimizer=adapter,
        evaluator=_root_at(5e-11),
        max_iter=16,
    ).run()

    extra = _search_outcome_extra(session)

    # Four expansions leave the bracket eight halvings wide at 16 evaluations,
    # and eight is exactly half the budget: granted, and closed.
    assert extra["search"] == {
        "converged": True,
        "stopping_rule": "rel_tol",
        "max_iter": 16,
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
        session = CalibrationEngine(
            space=adapter.space, optimizer=adapter, evaluator=_root_at(4e-3), max_iter=14
        ).run()

    extra = _search_outcome_extra(session)

    assert extra["search"] == {
        "converged": False,
        "stopping_rule": "rel_tol",
        "max_iter": 14,
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
    session = _run(adapter, 2.09e-4, AUTO_BUDGET)

    bracket = _search_outcome_extra(session)["bracket"]

    assert bracket["closed"] is True
    assert bracket["low"] <= 2.09e-4 <= bracket["high"]
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
            "stopping_rule": "xatol",
            "max_iter": 120,
            "extension": 0,
            "n_evaluations": 120,
        }
    return CalibrationReport(
        session_id="s1",
        method="scipy_nelder_mead",
        n_iterations=120,
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
    assert "before its stopping rule (xatol) was met" in caplog.text


def test_a_phase_built_on_an_unconverged_one_is_refused() -> None:
    decl = SimpleNamespace(name="steady", freeze_on_success=True, parameters=("K",))
    remaining = [SimpleNamespace(decl=SimpleNamespace(name="transient", depends_on="steady"))]

    with pytest.raises(CalibrationError) as caught:
        _require_result_for_dependents(decl, _report(converged=False), remaining)

    message = str(caught.value)
    assert "max_iter = 120, plus 0 granted once" in message
    assert "Raise max_iter or loosen the tolerance" in message
    assert "replays the trials already solved from the cache" in message
    assert "['transient']" in message


def _session_that(*, converged: bool) -> SimpleNamespace:
    return SimpleNamespace(
        converged=converged,
        stopping_rule="rel_tol",
        history=[None] * 17,
        max_iter=15,
        extension=2,
    )


def test_an_unconverged_search_closes_its_session_as_partial() -> None:
    status, error = _status_of_the_search(_session_that(converged=False), "completed", None)

    assert status == "partial"
    assert error == (
        "stopping rule (rel_tol) not met after 17 evaluations (max_iter = 15, extension = 2)"
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
# The simplex, an engine with a rule it cannot count
# --------------------------------------------------------------------------- #


def _two_dimensional_space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="K", lower=1.0, upper=1.0e3, transform="log"),
            CalibParameter(name="S", lower=1.0, upper=1.0e3, transform="log"),
        ]
    )


def _rosenbrock(sugg: ParamSuggestion) -> EvaluationResult:
    """A valley the simplex crawls along, far from any tight tolerance in 20 steps."""
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


def test_a_simplex_that_spends_its_budget_gets_no_extension(caplog) -> None:
    space = _two_dimensional_space()
    optimizer = ScipyNelderMead(space, maxiter=1000, maxfev=1000, xatol=1e-12, fatol=1e-14)
    engine = CalibrationEngine(space=space, optimizer=optimizer, evaluator=_rosenbrock, max_iter=20)
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
