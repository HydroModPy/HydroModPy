"""Tests of `optim.adapters.bisection_adapter`."""

from __future__ import annotations

import json
import logging
import math
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.adapters.bisection_adapter import (
    LOG10_ONE_PERCENT,
    BisectionAdapter,
    root_search_budget,
    roots_scored,
    signed_residual,
)
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.method_config import validate_method_kwargs
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    available_optimizers,
    build_optimizer,
    engine_traits,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import AUTO_BUDGET
from hydromodpy.calibration.preflight import _check_the_budgets
from hydromodpy.calibration.runners.cli_runner import (
    _closes_two_roots,
    _engine_kwargs,
    _r_optim_verdict_extra,
    _search_outcome_extra,
    load_toml_calibration,
)
from hydromodpy.calibration.runners.staged_runner import _phase_config
from hydromodpy.core.exceptions import ObjectiveError, OptimizerError
from tests.unit.calibration._factories_search import make_space, result_of, run_engine, staircase

# From test_bisection_adapter.py
# The one-dimensional root search, against a residual with a known root.


ROOT__bisection_adapter = 600.0


def _space(lower: float = 1.0, upper: float = 1.0e5, name: str = "K") -> ParameterSpace:
    return make_space((name, lower, upper, "log"))


def _evaluate(
    suggestion, *, root: float = ROOT__bisection_adapter, sign: float = 1.0
) -> EvaluationResult:
    """A staircase residual: positive below the root, negative above it.

    A staircase on purpose, and one that never lands on zero. The real
    criterion is a step function that jumps over its root rather than reaching
    it, so a search leaning on a smooth residual would pass here and fail on a
    catchment.
    """
    value = float(next(iter(suggestion.values.values())))
    residual = sign * staircase(root, value)
    return result_of(
        suggestion, abs(residual), components={"net.J_signed": residual, "net.J": abs(residual)}
    )


def _run(adapter, *, max_trials: int = 40, **kwargs) -> list[EvaluationResult]:
    """Drive the adapter the way the engine does: ask, evaluate, tell."""
    history: list[EvaluationResult] = []
    while len(history) < max_trials:
        suggestions = adapter.ask(n=1)
        if not suggestions:
            break
        results = [_evaluate(sugg, **kwargs) for sugg in suggestions]
        history.extend(results)
        adapter.tell(results)
        if adapter.converged():
            break
    return history


class TestRegistration:
    def test_the_method_is_registered(self) -> None:
        assert "bisection" in available_optimizers()

    def test_its_kwargs_validate_against_the_frozen_union(self) -> None:
        config = validate_method_kwargs("bisection", {"sweep_points": 0, "rel_tol": 0.01})
        assert config.method == "bisection"

    def test_a_foreign_kwarg_is_refused_at_config_time(self) -> None:
        # Registering the adapter is not enough: without an entry in the union
        # a typo would only surface inside the constructor.
        with pytest.raises(Exception, match="popsize"):
            validate_method_kwargs("bisection", {"popsize": 6})

    def test_it_builds_through_the_registry(self) -> None:
        optimizer = build_optimizer("bisection", _space(), seed=42)
        assert isinstance(optimizer, BisectionAdapter)


class TestDimension:
    def test_a_two_parameter_space_is_refused(self) -> None:
        space = ParameterSpace(
            [
                CalibParameter(name="K", lower=1.0, upper=10.0),
                CalibParameter(name="Sy", lower=0.01, upper=0.3),
            ]
        )
        with pytest.raises(OptimizerError, match="searches one parameter"):
            BisectionAdapter(space)


class TestRootSearch:
    def test_it_closes_the_bracket_on_the_root(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=7)
        _run(adapter)

        assert adapter.converged()
        low, high = adapter.bracket
        assert low <= math.log10(ROOT__bisection_adapter) <= high
        assert high - low <= math.log10(1.01)

    def test_the_stopping_rule_is_the_bracket_and_not_the_residual(self) -> None:
        # The residual is a staircase that steps over zero without landing
        # on it, so a search stopping on its size would never stop.
        adapter = BisectionAdapter(_space(), sweep_points=0)
        history = _run(adapter)

        assert adapter.converged()
        # The residual never reaches zero, yet the search stops.
        assert min(abs(r.cost) for r in history) > 0.0
        low, high = adapter.bracket
        assert high - low <= math.log10(1.01)

    def test_the_budget_matches_the_arithmetic(self) -> None:
        # Five decades to close to one per cent: two ends plus
        # ceil(log2(5 / log10(1.01))) halvings.
        adapter = BisectionAdapter(_space(1.0, 1.0e5), sweep_points=0)
        history = _run(adapter)
        expected = 2 + math.ceil(math.log2(5.0 / LOG10_ONE_PERCENT))
        assert len(history) <= expected + 1

    def test_the_pure_bisection_of_the_paper_is_available(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=0)
        first = adapter.ask(n=4)
        # Only the two ends of the interval, whatever the batch size asks for.
        assert len(first) == 2

    def test_the_sweep_runs_before_the_bisection(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=7)
        assert len(adapter.ask(n=7)) == 7

    def test_the_best_trial_is_the_one_closest_to_zero(self) -> None:
        # The cost carries the absolute residual, so the lowest cost is the
        # nearest to the root and never the most negative one.
        adapter = BisectionAdapter(_space(), sweep_points=5)
        history = _run(adapter)
        best = adapter.best()
        assert best is not None
        assert best.cost == min(r.cost for r in history)

    def test_it_returns_an_evaluated_point_not_the_midpoint(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=5)
        history = _run(adapter)
        assert adapter.best().trial_id in {r.trial_id for r in history}


class TestRefusal:
    def test_a_bracket_without_a_sign_change_raises(self) -> None:
        adapter = BisectionAdapter(_space(1.0, 10.0), sweep_points=3, bracket_expand=0)
        with pytest.raises(OptimizerError, match="keeps the same sign"):
            # The root sits far above the interval, so every residual is positive.
            _run(adapter, root=1.0e9)

    def test_the_refusal_names_both_ends(self) -> None:
        adapter = BisectionAdapter(_space(1.0, 10.0), sweep_points=3, bracket_expand=0)
        with pytest.raises(OptimizerError) as failure:
            _run(adapter, root=1.0e9)
        message = str(failure.value)
        assert "J_signed" in message
        assert message.count("at K =") == 2

    def test_it_widens_the_bracket_before_giving_up(self) -> None:
        # The root is one decade above the declared interval: one expansion
        # finds it rather than refusing.
        adapter = BisectionAdapter(_space(1.0, 100.0), sweep_points=3, bracket_expand=4)
        _run(adapter, root=500.0)
        assert adapter.converged()
        low, high = adapter.bracket
        assert low <= math.log10(500.0) <= high

    def test_a_trial_without_the_signed_component_is_refused(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=0)
        suggestion = adapter.ask(n=1)[0]
        blind = result_of(suggestion, 1.0, components={"rmse": 1.0})
        with pytest.raises(ObjectiveError, match="published no 'J_signed'"):
            adapter.tell([blind])


class TestSignedComponentLookup:
    def test_a_bare_key_is_found(self) -> None:
        assert signed_residual({"J_signed": -2.0}) == -2.0

    def test_a_prefixed_key_is_found(self) -> None:
        assert signed_residual({"net.J_signed": 3.0}) == 3.0

    def test_two_candidates_are_an_error(self) -> None:
        with pytest.raises(OptimizerError, match="several outputs"):
            signed_residual({"a.J_signed": 1.0, "b.J_signed": 2.0})

    def test_an_absent_key_is_not_an_error_here(self) -> None:
        assert signed_residual({"rmse": 1.0}) is None
        assert signed_residual(None) is None


class TestTransform:
    """The whole search walks a log10 variable, so it must be given one."""

    def test_an_identity_transform_parameter_is_refused(self) -> None:
        # Bounds [1e-9, 1e-3] in identity space are 1e-3 wide, which is already
        # below the tolerance: the search would report convergence on a bracket
        # a factor 1e6 wide, and _expand would subtract 1 m/s from a K.
        space = ParameterSpace([CalibParameter(name="K", lower=1.0e-9, upper=1.0e-3)])
        with pytest.raises(OptimizerError) as failure:
            BisectionAdapter(space)
        message = str(failure.value)
        assert "K" in message
        assert "identity" in message
        assert 'search_space = "log"' in message

    def test_a_logit_transform_parameter_is_refused(self) -> None:
        space = ParameterSpace(
            [CalibParameter(name="Sy", lower=0.01, upper=0.3, search_space="logit")]
        )
        with pytest.raises(OptimizerError, match="logit"):
            BisectionAdapter(space)

    def test_a_log_parameter_is_accepted(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=0)
        assert adapter.ask(n=2)

    def test_an_identity_space_does_not_report_convergence_after_the_sweep(self) -> None:
        # The regression, stated as behavior: no adapter reaches a converged
        # state on an untransformed parameter.
        space = ParameterSpace([CalibParameter(name="K", lower=1.0e-9, upper=1.0e-3)])
        with pytest.raises(OptimizerError):
            BisectionAdapter(space, sweep_points=7)


# From test_bisection_outside_bounds.py
# A root found outside the declared bounds says something about the declared bounds.
#
# The search widens its bracket a decade at a time, which is what lets it find a
# sign change a cautious pair of bounds missed. Several decades out is a different matter:
# it is usually the residual failing to respond to the parameter at all. Measured
# on the Nancon with the streams in SFR, the simulated network holds the reaches
# by construction whatever the conductivity, the residual stays positive across
# the whole declared interval, and the search closes three decades above it on a
# value that means nothing while r_optim reports 1.5, inside its validity bound.


def test_a_root_inside_the_bounds_says_nothing(caplog) -> None:
    adapter = BisectionAdapter(_space(upper=1.0e3), sweep_points=5, bracket_expand=4)
    _run(adapter, max_trials=60, root=50.0)
    with caplog.at_level(logging.WARNING):
        adapter.best()

    assert "OUTSIDE the declared bounds" not in caplog.text


def test_a_root_above_the_declared_interval_is_reported(caplog) -> None:
    # The zero sits two decades above the declared upper bound, which the
    # search only reaches by expanding.
    adapter = BisectionAdapter(_space(upper=1.0e3), sweep_points=5, bracket_expand=4)
    _run(adapter, max_trials=60, root=1.0e5)
    with caplog.at_level(logging.WARNING):
        winner = adapter.best()

    assert winner is not None
    assert "OUTSIDE the declared bounds" in caplog.text
    assert "does not respond to this parameter" in caplog.text
    assert "n_excess" in caplog.text


def test_a_bracket_that_never_expanded_is_never_reported(caplog) -> None:
    adapter = BisectionAdapter(_space(upper=1.0e3), sweep_points=5, bracket_expand=0)
    _run(adapter, max_trials=60, root=50.0)
    with caplog.at_level(logging.WARNING):
        adapter.best()

    assert "OUTSIDE the declared bounds" not in caplog.text


def test_nothing_evaluated_means_nothing_to_report() -> None:
    adapter = BisectionAdapter(_space(upper=1.0e3), sweep_points=3, bracket_expand=0)
    assert adapter.best() is None


# From test_the_root_search_answers_inside_its_bracket.py
# The trial the root search returns lies inside the bracket it closed.
#
# The residual steps rather than slides, so near the root many trials share one
# ``abs(J)`` to the last digit. ``min`` returned the first one evaluated, and on
# the Nancon that was trial 13, tied with trial 15 and 0.6 % outside the final
# bracket. The bracket is where the root is, so the answer is taken inside it.


ROOT = 2.09e-4
PLATEAU = 0.05


def _stepped(sugg: ParamSuggestion) -> EvaluationResult:
    """Residual whose magnitude is exactly 2.913 m within PLATEAU decades of the root."""
    gap = math.log10(ROOT) - math.log10(float(sugg.values["K"]))
    magnitude = 2.913 + 1000.0 * max(0.0, abs(gap) - PLATEAU)
    residual = math.copysign(magnitude, gap)
    return result_of(sugg, abs(residual), components={"net.J_signed": residual})


def _close(
    adapter: BisectionAdapter, evaluate=_stepped
) -> tuple[list[EvaluationResult], dict[int, float]]:
    """Run the search to closure; return its history and log10 K of each trial."""
    history: list[EvaluationResult] = []
    where: dict[int, float] = {}
    for _ in range(100):
        suggestions = adapter.ask(1)
        if not suggestions:
            break
        for sugg in suggestions:
            where[sugg.trial_id] = math.log10(float(sugg.values["K"]))
        results = [evaluate(sugg) for sugg in suggestions]
        history.extend(results)
        adapter.tell(results)
        if adapter.converged():
            break
    return history, where


def _inside(value: float, low: float, high: float) -> bool:
    return low - 1e-12 <= value <= high + 1e-12


def test_a_tie_outside_the_bracket_loses_to_one_inside() -> None:
    adapter = BisectionAdapter(_space(1e-7, 1e-3), rel_tol=0.01, sweep_points=7)
    history, where = _close(adapter)
    low, high = adapter.bracket

    # The situation of the Nancon: the first trial of minimal cost lies outside.
    first_tie = min(history, key=lambda result: result.cost)
    assert not _inside(where[first_tie.trial_id], low, high)

    winner = adapter.best()

    assert winner is not None
    assert winner.cost == first_tie.cost
    assert _inside(where[winner.trial_id], low, high)


def test_a_lower_cost_outside_the_closed_bracket_is_not_the_answer() -> None:
    adapter = BisectionAdapter(_space(1e-7, 1e-3), rel_tol=0.01, sweep_points=7)

    def with_a_lucky_sweep_point(sugg: ParamSuggestion) -> EvaluationResult:
        result = _stepped(sugg)
        if sugg.trial_id == 1:
            # Far below the root, still positive, but the lowest abs(J) of all.
            return result_of(result, 0.5, components={"net.J_signed": 0.5})
        return result

    _, where = _close(adapter, with_a_lucky_sweep_point)
    low, high = adapter.bracket

    winner = adapter.best()

    assert winner is not None and winner.trial_id != 1
    assert _inside(where[winner.trial_id], low, high)


def test_the_answer_is_outside_only_when_nothing_completed_lies_inside(caplog) -> None:
    adapter = BisectionAdapter(_space(1e-7, 1e-3), rel_tol=0.01, sweep_points=3)
    suggestions = adapter.ask(3)
    residuals = {1: (5.0, "completed"), 2: (3.0, "crashed"), 3: (-3.0, "crashed")}
    adapter.tell(
        [
            EvaluationResult(
                trial_id=sugg.trial_id,
                sim_id=None,
                cost=abs(residuals[sugg.trial_id][0]),
                status=residuals[sugg.trial_id][1],
                components={"net.J_signed": residuals[sugg.trial_id][0]},
            )
            for sugg in suggestions
        ]
    )

    with caplog.at_level(logging.WARNING):
        winner = adapter.best()

    assert winner is not None and winner.trial_id == 1
    assert "No completed trial lies inside the final bracket" in caplog.text


def test_no_bracket_yet_returns_the_lowest_cost() -> None:
    adapter = BisectionAdapter(_space(1e-7, 1e-3), rel_tol=0.01, sweep_points=3)
    (suggestion,) = adapter.ask(1)
    result = _stepped(suggestion)
    adapter.tell([result])

    assert adapter.bracket is None
    assert adapter.best() is result
    assert adapter.bracket_record() is None


# From test_the_root_search_closes_one_root_per_bound.py
# A root search on two bounds closes one root per bound, then solves their mean once.
#
# The residuals are synthetic and monotone: a staircase per bound, positive below
# its root and negative above, which never lands on zero, as the criterion does
# on a catchment. The minimal (permanent) map needs more water than the maximal
# one, so its root sits at a lower conductivity.


NANCON_BOUNDS = (1e-7, 1e-3)
ROOT_MIN = 3.0e-6
ROOT_MAX = 2.0e-4
REL_TOL = 0.01


def _staircase(root: float, value: float) -> float:
    return staircase(root, value, 200.0)


def _two_bounds(
    *,
    root_min: float = ROOT_MIN,
    root_max: float = ROOT_MAX,
    weights: tuple[float, float] = (0.5, 0.5),
    fail: set[int] | None = None,
    seen: list[ParamSuggestion] | None = None,
):
    """Score a trial the way a network output with two bounds publishes it."""
    w_min, w_max = weights

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        if seen is not None:
            seen.append(sugg)
        if fail and sugg.trial_id in fail:
            return EvaluationResult(trial_id=sugg.trial_id, sim_id=None, cost=1e9, status="failed")
        value = float(sugg.values["K"])
        j_min = _staircase(root_min, value)
        j_max = _staircase(root_max, value)
        return result_of(
            sugg,
            w_min * abs(j_min) + w_max * abs(j_max),
            components={
                "net.n_bounds_scored": 2.0,
                "net.weight_minimal": w_min,
                "net.weight_maximal": w_max,
                "net.J_signed_minimal": j_min,
                "net.J_signed_maximal": j_max,
                "net.J_signed_minimal_y2001": j_min,
                "net.r_optim_minimal": 1.5,
                "net.r_optim_maximal": 2.5,
                "net.h_obs_minimal": 50.0,
                "net.h_obs_maximal": 50.0,
                "net.D_optim_minimal": 75.0,
                "net.D_optim_maximal": 125.0,
                "net.validity_length_m_minimal": 100.0,
                "net.validity_length_m_maximal": 110.0,
                "net.validity_length_provenance_minimal": 0.0,
                "net.validity_length_provenance_maximal": 2.0,
            },
        )

    return evaluate


def _one_bound(root: float = ROOT_MAX, *, n_bounds: bool = True):
    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        residual = _staircase(root, float(sugg.values["K"]))
        components = {"net.J_signed": residual, "net.J_signed_maximal": residual}
        if n_bounds:
            components["net.n_bounds_scored"] = 1.0
        return result_of(sugg, abs(residual), components=components)

    return evaluate


def _run__root_search_closes(
    adapter: BisectionAdapter, evaluator, max_trials: int | str = AUTO_BUDGET
):
    return run_engine(adapter.space, adapter, evaluator, max_trials)


def _two_root_adapter(**kwargs) -> BisectionAdapter:
    return BisectionAdapter(_space(*NANCON_BOUNDS), rel_tol=REL_TOL, roots=2, **kwargs)


# --------------------------------------------------------------------------- #
# Two roots, one sweep, one combined solve
# --------------------------------------------------------------------------- #
def test_each_bound_closes_its_own_bracket_around_its_root() -> None:
    adapter = _two_root_adapter()
    session = _run__root_search_closes(adapter, _two_bounds())

    assert session.converged
    brackets = adapter.brackets
    for bound, root in (("minimal", ROOT_MIN), ("maximal", ROOT_MAX)):
        low, high = brackets[bound]
        assert 10.0**low <= root <= 10.0**high
        assert high - low <= math.log10(1.0 + REL_TOL) + 1e-12


def test_the_value_is_the_weighted_geometric_mean_of_the_two_roots_and_was_solved() -> None:
    seen: list[ParamSuggestion] = []
    adapter = _two_root_adapter()
    session = _run__root_search_closes(adapter, _two_bounds(seen=seen))
    record = adapter.roots_record()
    best = session.best

    expected = 10.0 ** (
        0.5 * math.log10(record["minimal"]["k_star"])
        + 0.5 * math.log10(record["maximal"]["k_star"])
    )
    assert best is not None
    assert best.trial_id == record["combined_trial_id"] == seen[-1].trial_id
    assert seen[-1].source == "combined"
    assert float(seen[-1].values["K"]) == pytest.approx(expected, rel=1e-12)
    assert record["value"] == pytest.approx(expected, rel=1e-12)
    assert math.isclose(expected, math.sqrt(ROOT_MIN * ROOT_MAX), rel_tol=2 * REL_TOL)
    # Every number beside the value comes from that solve: above the minimal
    # root and below the maximal one, each residual has its own sign.
    assert best.components["net.J_signed_minimal"] < 0.0 < best.components["net.J_signed_maximal"]


def test_the_record_publishes_both_roots_their_spread_and_both_brackets() -> None:
    adapter = _two_root_adapter()
    _run__root_search_closes(adapter, _two_bounds())
    record = adapter.roots_record()

    assert record["parameter"] == "K"
    assert record["closed"] is True
    assert record["minimal"]["k_star"] == pytest.approx(ROOT_MIN, rel=REL_TOL)
    assert record["maximal"]["k_star"] == pytest.approx(ROOT_MAX, rel=REL_TOL)
    assert record["delta_log10"] == pytest.approx(math.log10(ROOT_MAX / ROOT_MIN), abs=0.01)
    for bound in ("minimal", "maximal"):
        entry = record[bound]
        assert entry["closed"] is True
        assert entry["low"] <= entry["k_star"] <= entry["high"]
        assert entry["relative_width"] <= REL_TOL + 1e-9
        assert entry["weight"] == 0.5
        assert entry["trial_id"] is not None
    assert adapter.bracket is None
    assert adapter.bracket_record() is None


def test_the_weights_move_the_value_between_the_roots() -> None:
    adapter = _two_root_adapter()
    session = _run__root_search_closes(adapter, _two_bounds(weights=(0.25, 0.75)))
    record = adapter.roots_record()

    expected = 10.0 ** (
        0.25 * math.log10(record["minimal"]["k_star"])
        + 0.75 * math.log10(record["maximal"]["k_star"])
    )
    assert session.best is not None
    assert record["value"] == pytest.approx(expected, rel=1e-12)
    assert record["minimal"]["weight"] == 0.25


def test_a_bound_weighted_zero_is_not_searched() -> None:
    # The maximal root lies far outside every expansion: searching it would refuse.
    seen: list[ParamSuggestion] = []
    adapter = BisectionAdapter(_space(*NANCON_BOUNDS), rel_tol=REL_TOL, bracket_expand=0)
    session = _run__root_search_closes(
        adapter, _two_bounds(root_max=1e3, weights=(1.0, 0.0), seen=seen)
    )

    assert session.converged
    assert adapter.roots == 1
    assert adapter.roots_record() is None
    assert all(sugg.source != "combined" for sugg in seen)
    assert float(session.best.components["net.J_signed_minimal"]) == pytest.approx(0.0, abs=0.01)
    low, high = adapter.bracket
    assert 10.0**low <= ROOT_MIN <= 10.0**high


def test_a_bound_without_a_sign_change_is_refused_by_name() -> None:
    adapter = BisectionAdapter(_space(*NANCON_BOUNDS), rel_tol=REL_TOL, roots=2, bracket_expand=1)
    with pytest.raises(OptimizerError, match="maximal bound.*J_signed_maximal"):
        _run__root_search_closes(adapter, _two_bounds(root_max=1e3))


def test_a_combined_value_that_fails_to_solve_has_not_converged(caplog) -> None:
    budget = root_search_budget(*NANCON_BOUNDS, roots=2).nominal
    adapter = _two_root_adapter()
    session = _run__root_search_closes(adapter, _two_bounds(fail={budget}))

    assert not session.converged
    assert adapter.roots_record()["combined_trial_id"] is None
    assert adapter.roots_record()["value"] is None
    # What stands in is a trial that solved, never the unsolved combined value.
    assert session.best is not None
    assert session.best.status == "completed"


# --------------------------------------------------------------------------- #
# The budget covers two roots
# --------------------------------------------------------------------------- #
def test_the_count_adds_the_second_root_and_the_combined_solve() -> None:
    one = root_search_budget(*NANCON_BOUNDS)
    two = root_search_budget(*NANCON_BOUNDS, roots=2)

    assert one.counts == (15, 17, 19, 21, 23)
    assert two.counts == (24, 26, 28, 30, 32)
    assert _two_root_adapter().counted_budget == two


def test_a_count_of_three_roots_is_refused() -> None:
    with pytest.raises(OptimizerError, match="one or two roots"):
        root_search_budget(*NANCON_BOUNDS, roots=3)
    with pytest.raises(OptimizerError, match="one or two roots"):
        BisectionAdapter(_space(*NANCON_BOUNDS), roots=0)


def test_two_roots_inside_the_bounds_spend_the_nominal_count() -> None:
    adapter = _two_root_adapter()
    session = _run__root_search_closes(adapter, _two_bounds())

    assert session.converged
    assert session.extension == 0
    assert len(session.history) == adapter.counted_budget.nominal == 24


@pytest.mark.parametrize(("root_min", "root_max"), [(3e-9, 2e-4), (3e-9, 3e-2), (2e-4, 3e-1)])
def test_auto_covers_two_roots_found_after_expansions(root_min: float, root_max: float) -> None:
    adapter = _two_root_adapter()
    session = _run__root_search_closes(adapter, _two_bounds(root_min=root_min, root_max=root_max))

    assert session.converged
    assert session.extension == 0
    assert len(session.history) <= adapter.counted_budget.worst
    record = adapter.roots_record()
    assert record["minimal"]["k_star"] == pytest.approx(root_min, rel=REL_TOL)
    assert record["maximal"]["k_star"] == pytest.approx(root_max, rel=REL_TOL)


def test_the_halvings_left_count_both_brackets_and_the_combined_solve() -> None:
    adapter = _two_root_adapter()
    evaluate = _two_bounds()
    for _ in range(7):
        adapter.tell([evaluate(sugg) for sugg in adapter.ask(1)])

    # Two brackets a sweep step wide, eight halvings each, and the combined solve.
    assert adapter.evaluations_remaining == 8 + 8 + 1


def test_a_budget_counted_for_one_root_says_so_and_still_converges(caplog) -> None:
    adapter = BisectionAdapter(_space(*NANCON_BOUNDS), rel_tol=REL_TOL)
    with caplog.at_level(logging.WARNING):
        session = _run__root_search_closes(adapter, _two_bounds(), max_trials=40)

    assert "counted for 1 root(s) and the outputs score 2" in caplog.text
    assert session.converged
    assert adapter.roots == 2


def test_a_residual_named_by_hand_is_one_root() -> None:
    adapter = BisectionAdapter(
        _space(*NANCON_BOUNDS), rel_tol=REL_TOL, roots=2, signed_component="J_signed_maximal"
    )
    session = _run__root_search_closes(adapter, _two_bounds())

    assert adapter.counted_budget == root_search_budget(*NANCON_BOUNDS)
    assert adapter.roots_record() is None
    low, high = adapter.bracket
    assert 10.0**low <= ROOT_MAX <= 10.0**high
    assert session.converged


# --------------------------------------------------------------------------- #
# One bound keeps today's search exactly
# --------------------------------------------------------------------------- #
def test_one_bound_asks_the_same_points_as_the_paper_search() -> None:
    today: list[ParamSuggestion] = []
    now: list[ParamSuggestion] = []
    plain = _one_bound(n_bounds=False)
    counted = _one_bound(n_bounds=True)
    first = BisectionAdapter(_space(*NANCON_BOUNDS), rel_tol=REL_TOL)
    second = BisectionAdapter(_space(*NANCON_BOUNDS), rel_tol=REL_TOL)
    run_engine(first.space, first, lambda sugg: (today.append(sugg), plain(sugg))[1], AUTO_BUDGET)
    session = run_engine(
        second.space, second, lambda sugg: (now.append(sugg), counted(sugg))[1], AUTO_BUDGET
    )

    assert [dict(sugg.values) for sugg in now] == [dict(sugg.values) for sugg in today]
    assert [sugg.source for sugg in now] == [sugg.source for sugg in today]
    assert len(now) == 15
    assert session.best.trial_id == first.best().trial_id
    assert second.roots_record() is None
    assert second.bracket_record() == first.bracket_record()


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #
def test_the_report_publishes_the_roots_and_no_single_bracket() -> None:
    adapter = _two_root_adapter()
    session = _run__root_search_closes(adapter, _two_bounds())

    extra = _search_outcome_extra(session)

    assert "bracket" not in extra
    assert extra["roots"] == adapter.roots_record()
    assert extra["search"]["converged"] is True
    assert extra["search"]["n_evaluations"] == 24


def test_no_interval_of_trials_is_put_around_a_value_between_two_roots() -> None:
    two = _two_root_adapter()
    one = BisectionAdapter(_space(*NANCON_BOUNDS), rel_tol=REL_TOL)

    assert _closes_two_roots(_run__root_search_closes(two, _two_bounds())) is True
    assert _closes_two_roots(_run__root_search_closes(one, _one_bound())) is False


class _Output:
    support = "network"
    on_roptim_violation = "warn"


def test_eq4_is_read_on_each_bound_in_the_cost() -> None:
    adapter = _two_root_adapter()
    session = _run__root_search_closes(adapter, _two_bounds())

    extra = _r_optim_verdict_extra({"net": _Output()}, session.best.components)

    verdicts = extra["r_optim_verdict"]
    assert set(verdicts) == {"net_minimal", "net_maximal"}
    assert verdicts["net_minimal"]["valid"] is True
    assert verdicts["net_minimal"]["D_optim"] == 75.0
    assert verdicts["net_maximal"]["valid"] is False
    assert verdicts["net_maximal"]["value"] == 2.5
    # Each bound is read against the length its own map resolved.
    assert verdicts["net_minimal"]["validity_length_m"] == 100.0
    assert verdicts["net_maximal"]["validity_length_m"] == 110.0
    assert verdicts["net_maximal"]["provenance"] == "declared_accuracy"


def test_eq4_skips_a_bound_weighted_zero() -> None:
    components = dict(
        _two_bounds(weights=(1.0, 0.0))(ParamSuggestion(trial_id=1, values={"K": 1e-5})).components
    )

    verdicts = _r_optim_verdict_extra({"net": _Output()}, components)["r_optim_verdict"]

    assert set(verdicts) == {"net_minimal"}


# --------------------------------------------------------------------------- #
# Read off the declarations, before any solve
# --------------------------------------------------------------------------- #
_TOML = """
[calibration]
method = "bisection"
max_trials = {max_trials}

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
units = "m/s"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "complete.gpkg"
{minimal}
{extent}

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""

_EXTENT = "[calibration.outputs.net.extent]"
_MINIMAL = 'minimal_stream_geometry_path = "permanent.gpkg"'


def _load(tmp_path: Path, *, max_trials: int = 20, minimal: bool = True, extent: str = _EXTENT):
    path = tmp_path / "calibration.toml"
    text = _TOML.format(max_trials=max_trials, minimal=_MINIMAL if minimal else "", extent=extent)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    for name in ("complete.gpkg", "permanent.gpkg"):
        (tmp_path / name).write_bytes(b"")
    cfg, _raw = load_toml_calibration(path)
    return cfg


def test_two_bounds_are_counted_as_two_roots(tmp_path: Path) -> None:
    cfg = _load(tmp_path)

    assert roots_scored(cfg.outputs.values()) == 2
    assert _engine_kwargs(cfg, _space(*NANCON_BOUNDS), start_at=None)["roots"] == 2


def test_the_root_search_is_told_the_width_the_engine_asks(tmp_path: Path) -> None:
    cfg = _load(tmp_path)

    assert _engine_kwargs(cfg, _space(*NANCON_BOUNDS), start_at=None)["batch"] == 1
    wide = cfg.model_copy(update={"parallel": 4})
    assert _engine_kwargs(wide, _space(*NANCON_BOUNDS), start_at=None)["batch"] == 4


@pytest.mark.parametrize(
    ("minimal", "extent"),
    [
        (False, _EXTENT),
        (True, ""),
        (True, _EXTENT + "\nweights = { minimal = 1.0, maximal = 0.0 }"),
    ],
)
def test_anything_short_of_two_weighted_bounds_is_one_root(
    tmp_path: Path, minimal: bool, extent: str
) -> None:
    cfg = _load(tmp_path, minimal=minimal, extent=extent)

    assert _engine_kwargs(cfg, _space(*NANCON_BOUNDS), start_at=None)["roots"] == 1


def test_the_preflight_counts_two_roots(tmp_path: Path) -> None:
    findings = _check_the_budgets(_load(tmp_path, max_trials=20))

    assert [finding.severity for finding in findings] == ["error"]
    assert "below the 24 evaluations" in findings[0].detail


def test_the_preflight_counts_one_root_without_the_minimal_map(tmp_path: Path) -> None:
    findings = _check_the_budgets(_load(tmp_path, max_trials=20, minimal=False))

    assert [finding.severity for finding in findings] == ["warning"]


_SINGLE_METRIC_TOML = """
[calibration]
method = "bisection"
max_trials = {max_trials}
variable = "net"
objective = "distance_gap"

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
units = "m/s"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "complete.gpkg"
minimal_stream_geometry_path = "permanent.gpkg"

[calibration.outputs.net.extent]
{phase}
"""

_SINGLE_METRIC_PHASE = """
[[calibration.phases]]
name = "steady"
parameters = ["K"]
variable = "net"
objective = "distance_gap"
max_trials = {max_trials}
"""


def _load_single_metric(tmp_path: Path, *, max_trials: int | str = 20, phase: bool = False):
    budget = f'"{max_trials}"' if isinstance(max_trials, str) else str(max_trials)
    text = _SINGLE_METRIC_TOML.format(
        max_trials=budget, phase=_SINGLE_METRIC_PHASE.format(max_trials=budget) if phase else ""
    )
    path = tmp_path / "calibration.toml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    for name in ("complete.gpkg", "permanent.gpkg"):
        (tmp_path / name).write_bytes(b"")
    cfg, _raw = load_toml_calibration(path)
    return cfg


def test_the_variable_route_counts_two_roots(tmp_path: Path) -> None:
    # The whole-file (objective, variable) pair keeps its output, so the
    # engine and the preflight count the same two roots.
    cfg = _load_single_metric(tmp_path)

    assert _engine_kwargs(cfg, _space(*NANCON_BOUNDS), start_at=None)["roots"] == 2
    findings = _check_the_budgets(cfg)
    assert [finding.severity for finding in findings] == ["error"]
    assert "below the 24 evaluations" in findings[0].detail


def test_the_preflight_counts_two_roots_on_a_single_metric_phase(tmp_path: Path) -> None:
    cfg = _load_single_metric(tmp_path, phase=True)

    findings = _check_the_budgets(cfg)
    assert [finding.severity for finding in findings] == ["error"]
    assert "below the 24 evaluations" in findings[0].detail


def test_a_single_metric_phase_on_two_bounds_is_counted_as_two_roots(tmp_path: Path) -> None:
    # The phase keeps the output its variable names, so the engine counts the
    # two roots the preflight counts.

    cfg = _load_single_metric(tmp_path, max_trials=AUTO_BUDGET, phase=True)
    phase_cfg = _phase_config(cfg, cfg.phases[0])

    assert _engine_kwargs(phase_cfg, _space(*NANCON_BOUNDS), start_at=None)["roots"] == 2


# From test_the_root_search_cuts_its_bracket_side_by_side.py
# A root search asked for several points cuts its bracket into that many parts.
#
# One point per ask is the binary search, trial for trial: the recording in
# ``golden/root_search_width_one_golden.json`` holds the trials it asked before
# it learnt to cut its bracket several points at a time. With ``n`` points per
# ask the sweep comes ``n`` points at a time, each round cuts a bracket into
# ``n + 1`` equal parts, and two brackets share a round. The root then lies in
# a bracket as narrow as the binary search's, found in far fewer rounds.
#
# The residuals are synthetic: a smooth log-linear one, a staircase that steps
# over zero without landing on it, as the criterion does on a catchment, and a
# wiggle with three crossings inside one sweep interval.


GOLDEN = Path(__file__).parent / "golden" / "root_search_width_one_golden.json"

BOUNDS = (1e-7, 1e-3)
TOL = math.log10(1.0 + REL_TOL)

WIDTHS = (1, 2, 4, 7)

SWEEP_LOW = -5.0
SWEEP_STEP = 2.0 / 3.0
WIGGLE = tuple(SWEEP_LOW + fraction * SWEEP_STEP for fraction in (0.1, 0.3, 0.85))

Residual = Callable[[float], float]


def _smooth(root: float) -> Residual:
    return lambda value: math.log10(root) - math.log10(value)


def _step(root: float) -> Residual:
    return lambda value: staircase(root, value, 200.0)


def _wiggle(first: float, second: float, third: float) -> Residual:
    """Positive below *first*, negative up to *second*, positive up to *third*, then negative."""

    def residual(value: float) -> float:
        x = math.log10(value)
        if x < first:
            return first - x + 0.01
        if x < second:
            return -(min(x - first, second - x) + 0.01)
        if x < third:
            return min(x - second, third - x) + 0.01
        return -(x - third + 0.01)

    return residual


def _one(residual: Residual):
    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        value = residual(float(sugg.values["K"]))
        return result_of(sugg, abs(value), components={"net.J_signed": value})

    return evaluate


def _two(minimal: Residual, maximal: Residual):
    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        value = float(sugg.values["K"])
        j_min, j_max = minimal(value), maximal(value)
        return result_of(
            sugg,
            0.5 * abs(j_min) + 0.5 * abs(j_max),
            components={
                "net.n_bounds_scored": 2.0,
                "net.weight_minimal": 0.5,
                "net.weight_maximal": 0.5,
                "net.J_signed_minimal": j_min,
                "net.J_signed_maximal": j_max,
            },
        )

    return evaluate


SCENARIOS = {
    "one_smooth": ({}, _one(_smooth(ROOT))),
    "one_step": ({}, _one(_step(ROOT))),
    "one_expanded": ({}, _one(_step(3e-2))),
    "one_pure": ({"sweep_points": 0}, _one(_smooth(6.1e-6))),
    "one_wiggle": ({}, _one(_wiggle(*WIGGLE))),
    "two_step": ({"roots": 2}, _two(_step(ROOT_MIN), _step(ROOT_MAX))),
    "two_smooth": ({"roots": 2}, _two(_smooth(ROOT_MIN), _smooth(ROOT_MAX))),
    "two_expanded": ({"roots": 2}, _two(_step(3e-9), _step(ROOT_MAX))),
}


def _close__root_search_cuts(
    adapter: BisectionAdapter, evaluate, width: int
) -> list[list[ParamSuggestion]]:
    """Ask *width* points, evaluate, tell, until the search stops; return each round."""
    rounds: list[list[ParamSuggestion]] = []
    for _ in range(200):
        suggestions = adapter.ask(width)
        if not suggestions:
            break
        rounds.append(suggestions)
        adapter.tell([evaluate(sugg) for sugg in suggestions])
        if adapter.converged():
            break
    return rounds


def _log(sugg: ParamSuggestion) -> float:
    return math.log10(float(sugg.values["K"]))


def _value(adapter: BisectionAdapter, rounds: list[list[ParamSuggestion]]) -> float:
    """The returned value, in decades."""
    record = adapter.roots_record()
    if record is not None:
        return math.log10(record["value"])
    best = adapter.best().trial_id
    return next(_log(sugg) for batch in rounds for sugg in batch if sugg.trial_id == best)


def _contains(bracket: tuple[float, float], x: float) -> bool:
    low, high = bracket
    return low - 1e-12 <= x <= high + 1e-12


# --------------------------------------------------------------------------- #
# One point per ask is the binary search, trial for trial
# --------------------------------------------------------------------------- #
def _golden() -> dict:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_one_point_per_ask_asks_the_trials_of_the_binary_search(name: str) -> None:
    recorded = _golden()[name]
    options, evaluate = SCENARIOS[name]
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, **options)

    rounds = _close__root_search_cuts(adapter, evaluate, 1)

    trials = [[float(sugg.values["K"]), sugg.source] for batch in rounds for sugg in batch]
    assert trials == recorded["trials"]
    assert all(len(batch) == 1 for batch in rounds)
    assert adapter.converged()
    assert adapter.best().trial_id == recorded["best_trial_id"]
    assert list(adapter.counted_budget.counts) == recorded["counts"]
    if "bracket" in recorded:
        record = adapter.bracket_record()
        assert [record["low"], record["high"]] == recorded["bracket"]
    else:
        record = adapter.roots_record()
        for bound in ("minimal", "maximal"):
            assert [record[bound]["low"], record[bound]["high"]] == recorded["roots"][bound]
        assert record["value"] == recorded["roots"]["value"]


# --------------------------------------------------------------------------- #
# The sweep is handed out whole, in order
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("width", "sizes"), [(2, [2, 2, 2, 1]), (4, [4, 3]), (7, [7])])
def test_the_sweep_is_handed_out_n_points_at_a_time_in_order(width: int, sizes: list[int]) -> None:
    recorded = [trial[0] for trial in _golden()["one_smooth"]["trials"][:7]]
    options, evaluate = SCENARIOS["one_smooth"]
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, **options)

    rounds = _close__root_search_cuts(adapter, evaluate, width)
    sweep = [batch for batch in rounds if batch[0].source == "sweep"]

    assert [len(batch) for batch in sweep] == sizes
    assert [float(sugg.values["K"]) for batch in sweep for sugg in batch] == recorded


# --------------------------------------------------------------------------- #
# Every width closes a bracket around the root the binary search closes
# --------------------------------------------------------------------------- #
ONE_ROOT_ROUNDS = {1: (15, 15), 2: (9, 16), 4: (6, 20), 7: (4, 23)}

TWO_ROOT_ROUNDS = {1: (24, 24), 2: (13, 24), 4: (8, 26), 7: (6, 31)}


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("shape", [_smooth, _step])
def test_one_root_closes_where_the_binary_search_closes_in_fewer_rounds(
    shape: Callable[[float], Residual], width: int
) -> None:
    evaluate = _one(shape(ROOT))
    binary = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL)
    binary_rounds = _close__root_search_cuts(binary, evaluate, 1)
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL)

    rounds = _close__root_search_cuts(adapter, evaluate, width)

    root = math.log10(ROOT)
    low, high = adapter.bracket
    value = _value(adapter, rounds)
    assert adapter.converged()
    assert high - low <= TOL + 1e-12
    assert _contains(adapter.bracket, root) and _contains(binary.bracket, root)
    # The value is a trial inside a bracket one stopping width wide around the
    # root, so it lies within that width of the root and of the binary answer
    # up to two: a staircase ties both ends of a bracket, and either is returned.
    assert _contains(adapter.bracket, value)
    assert abs(value - _value(binary, binary_rounds)) <= 2.0 * TOL
    assert (len(rounds), sum(len(batch) for batch in rounds)) == ONE_ROOT_ROUNDS[width]
    assert sum(len(batch) for batch in rounds) == adapter.counted_budget.nominal
    assert adapter.bracket_record()["closed"] is True


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("shape", [_smooth, _step])
def test_two_roots_close_where_the_binary_search_closes_in_fewer_rounds(
    shape: Callable[[float], Residual], width: int
) -> None:
    evaluate = _two(shape(ROOT_MIN), shape(ROOT_MAX))
    binary = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, roots=2)
    binary_rounds = _close__root_search_cuts(binary, evaluate, 1)
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, roots=2)

    rounds = _close__root_search_cuts(adapter, evaluate, width)

    assert adapter.converged()
    record = adapter.roots_record()
    for bound, root in (("minimal", ROOT_MIN), ("maximal", ROOT_MAX)):
        bracket = adapter.brackets[bound]
        assert bracket[1] - bracket[0] <= TOL + 1e-12
        assert _contains(bracket, math.log10(root))
        assert _contains(binary.brackets[bound], math.log10(root))
        assert record[bound]["closed"] is True
        assert abs(math.log10(record[bound]["k_star"]) - math.log10(root)) <= TOL
    assert abs(_value(adapter, rounds) - _value(binary, binary_rounds)) <= 2.0 * TOL
    assert rounds[-1][0].source == "combined" and len(rounds[-1]) == 1
    assert (len(rounds), sum(len(batch) for batch in rounds)) == TWO_ROOT_ROUNDS[width]
    assert sum(len(batch) for batch in rounds) == adapter.counted_budget.nominal


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("name", ["one_expanded", "two_expanded"])
def test_a_root_found_after_expansions_stays_within_the_count(name: str, width: int) -> None:
    options, evaluate = SCENARIOS[name]
    binary = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, **options)
    binary_rounds = _close__root_search_cuts(binary, evaluate, 1)
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, **options)

    rounds = _close__root_search_cuts(adapter, evaluate, width)

    assert adapter.converged()
    assert sum(len(batch) for batch in rounds) <= adapter.counted_budget.worst
    assert abs(_value(adapter, rounds) - _value(binary, binary_rounds)) <= 2.0 * TOL


# --------------------------------------------------------------------------- #
# Several crossings in one round: the one binary bisection keeps
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("width", [1, 2, 3, 5, 7])
def test_several_crossings_in_one_round_keep_the_one_binary_bisection_keeps(width: int) -> None:
    # The wiggle crosses zero three times inside one sweep interval. Binary
    # bisection finds the midpoint positive, keeps the upper half, then the
    # upper quarter: it closes on the third crossing. Cut into 4, 6 or 8
    # parts, the round holds that midpoint, and its halvings are followed.
    options, evaluate = SCENARIOS["one_wiggle"]
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, **options)

    _close__root_search_cuts(adapter, evaluate, width)

    assert adapter.converged()
    assert _contains(adapter.bracket, WIGGLE[2])


def test_the_first_round_in_four_parts_keeps_the_upper_quarter() -> None:
    options, evaluate = SCENARIOS["one_wiggle"]
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, **options)
    for width in (3, 3, 1):
        adapter.tell([evaluate(sugg) for sugg in adapter.ask(width)])
    assert adapter.bracket == pytest.approx((SWEEP_LOW, SWEEP_LOW + SWEEP_STEP), abs=1e-12)

    results = [evaluate(sugg) for sugg in adapter.ask(3)]
    signs = [result.components["net.J_signed"] > 0.0 for result in results]
    adapter.tell(results)

    # Quarter, middle, three quarters: negative, positive, positive.
    assert signs == [False, True, True]
    low, high = adapter.bracket
    assert low == pytest.approx(SWEEP_LOW + 0.75 * SWEEP_STEP, abs=1e-12)
    assert high == pytest.approx(SWEEP_LOW + SWEEP_STEP, abs=1e-12)


def test_past_the_last_midpoint_evaluated_the_lowest_crossing_is_kept(caplog) -> None:
    # Cut into five parts, the round holds no midpoint: nothing says which
    # half binary bisection would keep, and the lowest crossing is kept, as
    # the sweep keeps the first of its crossings. The warning says the root
    # is not unique.
    options, evaluate = SCENARIOS["one_wiggle"]
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, **options)

    with caplog.at_level(logging.WARNING):
        _close__root_search_cuts(adapter, evaluate, 4)

    assert adapter.converged()
    assert _contains(adapter.bracket, WIGGLE[0])
    assert "changes sign 3 times" in caplog.text


# --------------------------------------------------------------------------- #
# Two brackets share each round
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("width", [2, 3, 4, 7])
def test_two_brackets_share_each_round_and_no_point_is_asked_twice(width: int) -> None:
    options, evaluate = SCENARIOS["two_step"]
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, **options)

    rounds = _close__root_search_cuts(adapter, evaluate, width)

    points = [round(_log(sugg), 9) for batch in rounds for sugg in batch]
    assert len(points) == len(set(points))
    first_cut = next(batch for batch in rounds if batch[0].source == "bisect")
    below = [sugg for sugg in first_cut if _log(sugg) < -4.5]
    # One each first, then the rest to the bracket that would stay widest.
    assert len(below) == math.ceil(width / 2)
    assert len(first_cut) - len(below) == width // 2


def test_a_bracket_both_bounds_share_is_cut_once() -> None:
    # Both roots lie in one sweep interval: the round cuts it into five
    # parts once, instead of proposing two cuts twice.
    evaluate = _two(_step(1.5e-4), _step(ROOT_MAX))
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, roots=2)

    rounds = _close__root_search_cuts(adapter, evaluate, 4)

    first_cut = rounds[2]
    low, high = -4.0 - 1.0 / 3.0, -3.0 - 2.0 / 3.0
    assert [sugg.source for sugg in first_cut] == ["bisect"] * 4
    assert [_log(sugg) for sugg in first_cut] == pytest.approx(
        [low + (high - low) * index / 5.0 for index in range(1, 5)], abs=1e-12
    )
    assert adapter.converged()
    record = adapter.roots_record()
    assert _contains(adapter.brackets["minimal"], math.log10(1.5e-4))
    assert _contains(adapter.brackets["maximal"], math.log10(ROOT_MAX))
    assert record["closed"] is True


# --------------------------------------------------------------------------- #
# The count follows the points asked at once
# --------------------------------------------------------------------------- #
def test_one_point_per_ask_keeps_the_count_of_the_binary_search() -> None:
    assert root_search_budget(*BOUNDS, batch=1).counts == (15, 17, 19, 21, 23)
    assert root_search_budget(*BOUNDS, roots=2, batch=1).counts == (24, 26, 28, 30, 32)


@pytest.mark.parametrize(
    ("batch", "one", "two"),
    [
        (2, (16, 19, 21, 23, 25), (24, 26, 28, 30, 32)),
        (4, (20, 22, 24, 26, 28), (26, 30, 32, 34, 36)),
        (7, (23, 26, 28, 30, 32), (31, 35, 37, 39, 41)),
    ],
)
def test_the_count_follows_the_points_asked_at_once(
    batch: int, one: tuple[int, ...], two: tuple[int, ...]
) -> None:
    assert root_search_budget(*BOUNDS, batch=batch).counts == one
    assert root_search_budget(*BOUNDS, roots=2, batch=batch).counts == two
    assert (
        BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, batch=batch).counted_budget.counts == one
    )


def test_the_adapter_counts_the_widest_ask_once_it_is_asked() -> None:
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, roots=2)
    assert adapter.counted_budget == root_search_budget(*BOUNDS, roots=2)

    adapter.ask(4)

    assert adapter.counted_budget == root_search_budget(*BOUNDS, roots=2, batch=4)


def test_a_batch_below_one_point_is_refused() -> None:
    with pytest.raises(OptimizerError, match="at least one point"):
        root_search_budget(*BOUNDS, batch=0)
    with pytest.raises(OptimizerError, match="at least one point"):
        BisectionAdapter(_space(*BOUNDS), batch=0)


@pytest.mark.parametrize(("name", "width"), [("one_step", 4), ("two_step", 4), ("two_step", 7)])
def test_the_evaluations_left_are_the_evaluations_spent(name: str, width: int) -> None:
    options, evaluate = SCENARIOS[name]
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, **options)
    sizes: list[int] = []
    left: list[int | None] = []
    for _ in range(50):
        suggestions = adapter.ask(width)
        if not suggestions:
            break
        adapter.tell([evaluate(sugg) for sugg in suggestions])
        sizes.append(len(suggestions))
        left.append(adapter.evaluations_remaining)
        if adapter.converged():
            break

    first = next(index for index, value in enumerate(left) if value is not None)
    # Once the sweep has found the brackets, the count left is what the nominal
    # count still holds, and each round spends exactly what it removes.
    assert left[first] == adapter.counted_budget.nominal - 7
    for index in range(first + 1, len(left)):
        assert left[index - 1] - left[index] == sizes[index]
    assert left[-1] == 0


# --------------------------------------------------------------------------- #
# Through the engine
# --------------------------------------------------------------------------- #
def _engine_run(parallel: int, **options):
    adapter = BisectionAdapter(_space(*BOUNDS), rel_tol=REL_TOL, roots=2, **options)
    rounds: list[int] = []
    ask = adapter.ask

    def counted_ask(n: int = 1) -> list[ParamSuggestion]:
        suggestions = ask(n)
        if suggestions:
            rounds.append(len(suggestions))
        return suggestions

    adapter.ask = counted_ask  # type: ignore[method-assign]
    session = run_engine(
        adapter.space,
        adapter,
        _two(_step(ROOT_MIN), _step(ROOT_MAX)),
        AUTO_BUDGET,
        parallel=parallel,
    )
    return adapter, session, rounds


@pytest.mark.parametrize("declared", [{}, {"batch": 4}])
def test_four_workers_find_the_roots_of_one_in_far_fewer_rounds(declared: dict) -> None:
    serial, serial_session, serial_rounds = _engine_run(1)
    wide, session, rounds = _engine_run(4, **declared)

    assert serial_session.converged and session.converged
    assert session.extension == 0
    one, four = serial.roots_record(), wide.roots_record()
    for bound in ("minimal", "maximal"):
        assert abs(math.log10(four[bound]["k_star"]) - math.log10(one[bound]["k_star"])) <= 2 * TOL
        assert four[bound]["closed"] is True
    assert abs(math.log10(four["value"]) - math.log10(one["value"])) <= 2 * TOL
    assert session.best.trial_id == four["combined_trial_id"]
    assert (len(serial_rounds), sum(serial_rounds)) == (24, 24)
    assert (len(rounds), sum(rounds)) == (8, 26)
    assert len(session.history) == 26
    assert wide.counted_budget == root_search_budget(*BOUNDS, roots=2, batch=4)


def test_the_root_search_declares_it_runs_trials_side_by_side() -> None:
    assert engine_traits("bisection").supports_parallel is True


# --------------------------------------------------------------------------- #
# The preflight counts the points the engine asks at once
# --------------------------------------------------------------------------- #
_TOML__root_search_cuts = """
[calibration]
method = "bisection"
max_trials = {max_trials}
{workers}

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
units = "m/s"

[calibration.outputs.net]
support = "network"
stream_geometry_path = "complete.gpkg"
minimal_stream_geometry_path = "permanent.gpkg"

[calibration.outputs.net.extent]

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
{phase}
"""

_PHASE = """
[[calibration.phases]]
name = "steady"
parameters = ["K"]
objective_blocks = ["network"]
max_trials = {max_trials}
{workers}
"""


def _load__root_search_cuts(
    tmp_path: Path, *, workers: str = "", phase: str | None = None, max_trials: int = 24
):
    text = _TOML__root_search_cuts.format(
        max_trials=max_trials,
        workers=workers,
        phase="" if phase is None else _PHASE.format(max_trials=max_trials, workers=phase),
    )
    path = tmp_path / "calibration.toml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    for name in ("complete.gpkg", "permanent.gpkg"):
        (tmp_path / name).write_bytes(b"")
    cfg, _raw = load_toml_calibration(path)
    return cfg


@pytest.mark.parametrize(
    ("workers", "phase", "severity"),
    [
        ("", None, "warning"),
        ("parallel = 4", None, "error"),
        ("parallel = 1\nbatch_size = 4", None, "error"),
        ("parallel = 4", "", "error"),
        ("", "parallel = 4", "error"),
        ("parallel = 4", "parallel = 1", "warning"),
    ],
)
def test_the_preflight_counts_the_points_asked_at_once(
    tmp_path: Path, workers: str, phase: str | None, severity: str
) -> None:
    # Two roots: 24 evaluations one point at a time, 26 four at a time.
    findings = _check_the_budgets(_load__root_search_cuts(tmp_path, workers=workers, phase=phase))

    assert [finding.severity for finding in findings] == [severity]
    if severity == "error":
        assert "below the 26 evaluations" in findings[0].detail
