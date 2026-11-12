"""Stopping state, evaluation budget and precision of a calibration search.

A search stops on its own rule (`rule_met`), on the end of its plan
(`plan_exhausted`) or on its budget (`budget_spent`). Budgets are numbers of
solves. A precision is a relative width on a parameter, translated to the option
each engine reads: decades for a log parameter, a fraction of the interval for a
linear one. Costs are dimensionless and parameters are searched in log10.
"""

from __future__ import annotations

import json
import logging
import math
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.config_network import MatchingHydrographicNetworkOptions
from hydromodpy.calibration.config_phases import CalibPhaseDecl
from hydromodpy.calibration.optim import stopping
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
    resolve_budget,
    search_width,
    settled,
    short_budget,
    stop_state,
    stopping_kwargs,
    stopping_rule,
)
from hydromodpy.calibration.preflight import _check_the_budgets
from hydromodpy.calibration.runners.document import load_toml_calibration
from hydromodpy.calibration.runners.search_record import search_outcome_extra
from hydromodpy.calibration.runners.session_scope import search_status
from hydromodpy.core.exceptions import OptimizerError
from hydromodpy.results.record.checks import BUDGET_RULE
from tests.unit.calibration._factories_search import result_of, run_engine

NANCON_BOUNDS = (1e-7, 1e-3)  # m/s
K = CalibParameter(name="K", lower=1e-8, upper=1e-2, search_space="log")
SY = CalibParameter(name="Sy", lower=1e-4, upper=0.5, search_space="log")
POROSITY = CalibParameter(name="n", lower=0.0, upper=0.4, search_space="identity")


def log_space(lower: float = 1.0, upper: float = 1.0e3) -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="K", lower=lower, upper=upper, search_space="log")])


def two_log_params() -> ParameterSpace:
    names = ("K", "S")
    return ParameterSpace(
        [CalibParameter(name=n, lower=1.0, upper=1.0e3, search_space="log") for n in names]
    )


def grid_space() -> ParameterSpace:
    return ParameterSpace(
        [CalibParameter(name=name, lower=0.0, upper=1.0) for name in ("a", "b", "c")]
    )


def bowl(sugg: ParamSuggestion) -> EvaluationResult:
    cost = sum((math.log10(float(value)) - 1.5) ** 2 for value in sugg.values.values())
    return result_of(sugg, cost)


def rosenbrock(sugg: ParamSuggestion) -> EvaluationResult:
    # A valley the simplex crawls along, far from any tight tolerance in 20 steps.
    x = math.log10(float(sugg.values["K"]))
    y = math.log10(float(sugg.values["S"]))
    return result_of(sugg, (1.0 - x) ** 2 + 100.0 * (y - x * x) ** 2)


def sum_of_values(suggestion) -> EvaluationResult:
    return result_of(
        suggestion,
        float(sum(suggestion.values.values())),
        metadata={"values": dict(suggestion.values)},
    )


def root_at(root: float, calls: list[int] | None = None):
    """A continuous residual, positive below *root* and negative above it."""

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        if calls is not None:
            calls.append(sugg.trial_id)
        residual = math.log10(root) - math.log10(float(sugg.values["K"]))
        return result_of(sugg, abs(residual), components={"net.J_signed": residual})

    return evaluate


def nancon(**kwargs) -> BisectionAdapter:
    return BisectionAdapter(log_space(*NANCON_BOUNDS), **kwargs)


def root_search(adapter: BisectionAdapter, root: float, max_trials: int | str):
    return run_engine(adapter.space, adapter, root_at(root), max_trials)


def tight_simplex() -> ScipyNelderMead:
    return ScipyNelderMead(two_log_params(), maxiter=1000, maxfev=1000, xatol=1e-12, fatol=1e-14)


class CutDesign:
    """A design engine whose plan the budget cut short, past the up-front refusal."""

    name = "cut"
    traits = EngineTraits()
    counted_budget = CountedBudget(counts=(25,), step="grid point")


class FarFromItsRule:
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


BUDGET_ONLY = SimpleNamespace(traits=EngineTraits())

STOP_STATES = [
    pytest.param(CutDesign(), False, True, "budget_spent", id="design cut short"),
    pytest.param(CutDesign(), True, True, "plan_exhausted", id="design done"),
    pytest.param(BUDGET_ONLY, True, False, "rule_met", id="rule met"),
    pytest.param(BUDGET_ONLY, True, True, "budget_spent", id="rule met on the last solve"),
    pytest.param(BUDGET_ONLY, False, True, "budget_spent", id="rule not met"),
]

SETTLED = [
    pytest.param("rule_met", "xatol", True, id="rule met"),
    pytest.param("plan_exhausted", "every grid point", True, id="plan exhausted"),
    pytest.param("budget_spent", BUDGET_RULE, True, id="budget engine spent its budget"),
    pytest.param("budget_spent", "xatol", False, id="rule engine spent its budget"),
    pytest.param("budget_spent", "every grid point", False, id="design cut short"),
]

# A relative precision of 10 % on a conductivity is 0.0414 decades wherever the
# value sits. A linear parameter has nothing to be relative to, so it takes a
# fraction of its interval.
WIDTHS = [
    pytest.param(K, 0.10, math.log10(1.1), id="log conductivity"),
    pytest.param(SY, 0.10, math.log10(1.1), id="log specific yield"),
    pytest.param(POROSITY, 0.05, 0.05 * 0.4, id="linear porosity"),
]

NELDER_MEAD_WIDTH = pytest.approx(math.log10(1.1))
KWARGS = [
    pytest.param(
        "scipy_nelder_mead",
        0.10,
        {},
        {"xatol": NELDER_MEAD_WIDTH, "fatol": 0.0, "fatol_rel": 0.10},
        id="nelder-mead absolute width and relative cost spread",
    ),
    pytest.param(
        "scipy_nelder_mead",
        0.10,
        {"fatol": 1e-6},
        {"xatol": NELDER_MEAD_WIDTH, "fatol": 1e-6},
        id="declared fatol kept as written",
    ),
    # rel_tol is already a relative width on the parameter's own value.
    pytest.param("bisection", 0.01, {}, {"rel_tol": 0.01}, id="root search unconverted"),
]

KWARGS_REFUSED = [
    pytest.param("scipy_nelder_mead", 0.10, {"xatol": 0.30}, "both set the", id="said twice"),
    # Dropping it silently would report a search that honored a request it never read.
    pytest.param("grid", 0.10, {}, "max_trials", id="engine that stops on its budget"),
    pytest.param("scipy_nelder_mead", -0.1, {}, "strictly positive, got -0.1", id="negative"),
    pytest.param("scipy_nelder_mead", 0.0, {}, "strictly positive, got 0.0", id="zero"),
]

BUDGET_FIELDS_REFUSED = [
    pytest.param({"max_trials": 0}, id="zero"),
    pytest.param({"max_trials": "many"}, id="word"),
]

PREFLIGHT_HEAD = """
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


def budget_findings(tmp_path: Path, **protocol):
    """Check the budgets of the matching protocol; ``protocol`` sets its keys as TOML values."""
    lines = "".join(f"{key} = {json.dumps(value)}\n" for key, value in protocol.items())
    path = tmp_path / "budget.toml"
    path.write_text(
        textwrap.dedent(PREFLIGHT_HEAD)
        + '[calibration.protocol]\nname = "matching_hydrographic_network"\n'
        + lines,
        encoding="utf-8",
    )
    (tmp_path / "network.gpkg").write_bytes(b"")
    cfg, _raw = load_toml_calibration(path)
    return _check_the_budgets(cfg)


@pytest.mark.parametrize(("engine", "met", "spent", "state"), STOP_STATES)
def test_stop_state(engine, met, spent, state) -> None:
    assert stop_state(engine, met=met, spent=spent) == state


@pytest.mark.parametrize(("state", "rule", "expected"), SETTLED)
def test_settled(state, rule, expected) -> None:
    assert settled(state, rule) is expected


def test_latin_hypercube_exhausts_its_plan() -> None:
    space = two_log_params()
    session = run_engine(space, build_optimizer("lhs", space, n_samples=6, seed=1), bowl, 6)

    assert len(space) == 2
    assert session.stop_state == "plan_exhausted"
    assert session.converged


def test_simplex_cut_by_the_budget(caplog) -> None:
    # The simplex has a rule it cannot count, so its budget is never extended.
    with caplog.at_level(logging.WARNING):
        session = run_engine(two_log_params(), tight_simplex(), rosenbrock, 20)

    assert session.stop_state == "budget_spent"
    assert session.stopping_rule == "xatol"
    assert not session.converged
    assert not session.settled
    assert search_status(session) == "partial"
    assert session.extension == 0
    assert len(session.history) == 20
    assert "Granting" not in caplog.text
    assert "did NOT converge" in caplog.text


def test_budget_engine_spends_its_budget(caplog) -> None:
    # A random search has no rule of its own, so it spends its budget by design.
    optimizer = build_optimizer("random_search", log_space(), seed=3)
    with caplog.at_level(logging.WARNING):
        session = run_engine(log_space(), optimizer, root_at(50.0), 4)

    assert session.stopping_rule == BUDGET_RULE
    assert session.stop_state == "budget_spent"
    assert not session.converged
    assert session.settled
    assert session.extension == 0
    assert len(session.history) == 4
    assert "Granting" not in caplog.text
    assert "the best of a budget-only search" in caplog.text


def test_stopping_rule_of_an_engine() -> None:
    assert stopping_rule(nancon()) == "rel_tol"
    assert stopping_rule(build_optimizer("random_search", log_space(), seed=1)) == BUDGET_RULE


def test_root_search_budget_is_a_count() -> None:
    # The sweep, one halving per step down to the tolerance, two solves per expansion.
    assert nancon().counted_budget.nominal == 15
    assert resolve_budget(nancon(), AUTO_BUDGET) == 23


def test_auto_budgets_the_worst_case() -> None:
    adapter = nancon()

    assert resolve_budget(adapter, AUTO_BUDGET) == 23
    assert root_search(adapter, 2.09e-4, AUTO_BUDGET).max_trials == 23


def test_auto_budget_of_uncounted_engine() -> None:
    optimizer = build_optimizer("random_search", log_space(), seed=1)

    assert resolve_budget(optimizer, AUTO_BUDGET) == UNCOUNTED_BUDGET == 100
    assert resolve_budget(optimizer, 12) == 12


def test_auto_budget_of_a_grid() -> None:
    # Three parameters on five points each are 125 points, not the uncounted 100.
    optimizer = build_optimizer("grid", grid_space(), points_per_dim=5)

    assert resolve_budget(optimizer, "auto") == 125


def test_whole_grid_is_visited() -> None:
    space = grid_space()
    optimizer = build_optimizer("grid", space, points_per_dim=[5, 5, 6])
    session = run_engine(space, optimizer, sum_of_values, "auto")

    assert len(session.history) == 150
    assert max(result.metadata["values"]["a"] for result in session.history) == 1.0


def test_budget_below_nominal_refused() -> None:
    adapter = nancon()
    calls: list[int] = []
    engine = CalibrationEngine(
        space=adapter.space, optimizer=adapter, evaluator=root_at(2.09e-4, calls), max_trials=10
    )

    with pytest.raises(OptimizerError) as caught:
        engine.run()

    assert calls == []
    assert "max_trials = 10 is below the 15 evaluations" in str(caught.value)
    assert '"auto" (23 here' in str(caught.value)


def test_budget_below_worst_case_warns(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        session = root_search(nancon(), 2.09e-4, 18)

    assert session.converged
    assert "max_trials = 18 covers 1 bracket expansion(s) of the 4" in caplog.text
    assert "the worst case needs 23" in caplog.text


def test_budget_above_worst_case_silent(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        session = root_search(nancon(), 2.09e-4, 23)

    assert session.converged
    assert caplog.text == ""


def test_verdict_on_a_declared_budget() -> None:
    counted = CountedBudget(counts=(15, 17, 19, 21, 23))

    assert short_budget(counted, 23) is None
    assert short_budget(counted, 40) is None
    assert short_budget(counted, 20)[0] == "warning"
    assert "covers 2 bracket expansion(s)" in short_budget(counted, 20)[1]
    assert short_budget(counted, 15)[0] == "warning"
    assert short_budget(counted, 14)[0] == "error"


def test_two_halvings_short_granted(caplog) -> None:
    # One expansion needs 17 evaluations. 15 leaves the bracket two halvings wide.
    with caplog.at_level(logging.WARNING):
        session = root_search(nancon(), 3e-3, 15)

    assert session.converged
    assert session.max_trials == 15
    assert session.extension == 2
    assert len(session.history) == 17
    assert "needs 2 more to meet its stopping rule (rel_tol). Granting exactly those 2" in (
        caplog.text
    )


def test_halvings_still_needed() -> None:
    adapter = nancon()
    evaluate = root_at(3e-3)
    assert adapter.evaluations_remaining is None

    # Sweep 7, one expansion 2, then three of the eight halvings.
    for _ in range(12):
        adapter.tell([evaluate(suggestion) for suggestion in adapter.ask(1)])
    assert adapter.evaluations_remaining == 5

    while not adapter.converged():
        adapter.tell([evaluate(suggestion) for suggestion in adapter.ask(1)])
    assert adapter.evaluations_remaining == 0


def test_need_beyond_half_not_granted(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        session = run_engine(log_space(), FarFromItsRule(), root_at(50.0), 10)

    assert not session.converged
    assert session.extension == 0
    assert len(session.history) == 10
    assert "still needs 50" in caplog.text
    assert "nothing is granted" in caplog.text


def test_budget_fields_read() -> None:
    assert MatchingHydrographicNetworkOptions(
        name="matching_hydrographic_network"
    ).steady_max_trials
    assert CalibPhaseDecl(name="p", parameters=["K"]).max_trials is None
    assert CalibPhaseDecl(name="p", parameters=["K"], max_trials="auto").max_trials == AUTO_BUDGET
    assert CalibPhaseDecl(name="p", parameters=["K"], max_trials=12).max_trials == 12


def test_preflight_budget_below_nominal(tmp_path: Path) -> None:
    findings = budget_findings(tmp_path, steady_max_trials=10)

    assert [finding.severity for finding in findings] == ["error"]
    assert findings[0].path == "calibration.phases"
    assert findings[0].detail.startswith("'steady_conductivity': ")
    assert "max_trials = 10 is below the 15 evaluations" in findings[0].detail
    assert "steady_max_trials" in findings[0].detail


def test_preflight_budget_below_worst_case(tmp_path: Path) -> None:
    findings = budget_findings(tmp_path, steady_max_trials=18)

    assert [finding.severity for finding in findings] == ["warning"]
    assert "covers 1 bracket expansion(s) of the 4" in findings[0].detail


@pytest.mark.parametrize("budget", ["auto", 23, 40])
def test_preflight_budget_passes(tmp_path: Path, budget) -> None:
    assert budget_findings(tmp_path, steady_max_trials=budget) == []


def test_report_records_the_closed_bracket() -> None:
    adapter = nancon()
    session = root_search(adapter, 5e-11, 16)

    extra = search_outcome_extra(session)

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


def test_report_open_bracket(caplog) -> None:
    # A pure bisection on [1, 1.5] at 0.01 %: 14 evaluations inside the bounds.
    # A root three decades out spends 8 on the bounds and the expansions, 6 on
    # halvings, and still needs 9, more than half of 14.
    adapter = BisectionAdapter(log_space(1.0, 1.5), sweep_points=0, rel_tol=0.0001)
    assert adapter.counted_budget.nominal == 14
    with caplog.at_level(logging.WARNING):
        session = root_search(adapter, 4e-3, 14)

    extra = search_outcome_extra(session)

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


def test_report_bracket_in_physical_units() -> None:
    session = root_search(nancon(), 2.09e-4, AUTO_BUDGET)

    bracket = search_outcome_extra(session)["bracket"]

    assert bracket["closed"] is True
    assert bracket["low"] <= 2.09e-4 <= bracket["high"]
    assert bracket["relative_width"] == pytest.approx(bracket["high"] / bracket["low"] - 1.0)
    assert bracket["relative_width"] <= 0.01


@pytest.mark.parametrize(("parameter", "precision", "width"), WIDTHS)
def test_search_width(parameter, precision, width) -> None:
    assert search_width(parameter, precision) == pytest.approx(width)


@pytest.mark.parametrize(("method", "precision", "declared", "expected"), KWARGS)
def test_stopping_kwargs(method, precision, declared, expected) -> None:
    kwargs = stopping_kwargs(method, ParameterSpace([K]), precision=precision, declared=declared)

    assert kwargs == expected


def test_strictest_parameter_sets_the_width() -> None:
    # One number stops the search for every parameter at once.
    kwargs = stopping_kwargs("scipy_nelder_mead", ParameterSpace([K, POROSITY]), precision=0.05)

    assert kwargs["xatol"] == pytest.approx(
        min(search_width(K, 0.05), search_width(POROSITY, 0.05))
    )


def test_precision_joins_the_declared_kwargs() -> None:
    kwargs = stopping_kwargs(
        "scipy_nelder_mead", ParameterSpace([K]), precision=0.10, declared={"maxiter": 30}
    )

    assert kwargs["maxiter"] == 30
    assert kwargs["xatol"] == pytest.approx(math.log10(1.1))


def test_built_optimizers_accept_the_translation() -> None:
    space = ParameterSpace([K])
    for method, extra in (("scipy_nelder_mead", {}), ("bisection", {"sweep_points": 0})):
        kwargs = stopping_kwargs(method, space, precision=0.05, declared=extra)
        assert build_optimizer(method, space, **kwargs) is not None


@pytest.mark.parametrize(
    ("method", "expected"), [("cma_es", {"max_trials": 7}), ("scipy_nelder_mead", {})]
)
def test_budget_kwargs(method, expected) -> None:
    assert stopping.budget_kwargs(method, 7) == expected


def test_engine_without_precision_reading_refused(monkeypatch) -> None:
    undeclared = EngineTraits(precision_option="xatol", precision_reads=None)
    monkeypatch.setattr(stopping, "engine_traits", lambda method: undeclared)

    with pytest.raises(ValueError, match="without declaring how that option reads"):
        stopping_kwargs("scipy_nelder_mead", ParameterSpace([K]), precision=0.1)


@pytest.mark.parametrize(("method", "precision", "declared", "message"), KWARGS_REFUSED)
def test_stopping_kwargs_refusals(method, precision, declared, message) -> None:
    with pytest.raises(ValueError, match=message):
        stopping_kwargs(method, ParameterSpace([K]), precision=precision, declared=declared)


def test_precision_without_parameters_is_refused() -> None:
    with pytest.raises(ValueError, match="declares none"):
        stopping_kwargs("scipy_nelder_mead", ParameterSpace([]), precision=0.1)


def test_budget_refusals() -> None:
    with pytest.raises(ValueError, match="0 < lower < upper"):
        root_search_budget(0.0, 1.0)
    with pytest.raises(ValueError, match="rel_tol"):
        root_search_budget(1.0, 10.0, rel_tol=0.0)
    with pytest.raises(ValueError, match="auto"):
        resolve_budget(build_optimizer("random_search", log_space(), seed=1), "many")


@pytest.mark.parametrize("fields", BUDGET_FIELDS_REFUSED)
def test_budget_field_refusals(fields) -> None:
    with pytest.raises(ValueError):
        CalibPhaseDecl(name="p", parameters=["K"], **fields)
