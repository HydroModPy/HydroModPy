"""Tests of `optim.adapters.bisection_adapter`."""

from __future__ import annotations

import copy
import json
import logging
import math
import textwrap
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from hydromodpy.calibration.optim.adapters.bisection_adapter import (
    BOUNDS_COMPONENT,
    LOG10_ONE_PERCENT,
    BisectionAdapter,
    RootTarget,
    root_search_budget,
    signed_residual,
)
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import EvaluationResult, ParamSuggestion
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import AUTO_BUDGET
from hydromodpy.calibration.runners.document import load_toml_calibration
from hydromodpy.calibration.runners.search import _engine_kwargs
from hydromodpy.calibration.runners.search_record import (
    closes_two_roots,
    r_optim_verdict_extra,
    search_outcome_extra,
)
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
    def test_the_budget_matches_the_arithmetic(self) -> None:
        # Five decades to close to one per cent: two ends plus
        # ceil(log2(5 / log10(1.01))) halvings.
        adapter = BisectionAdapter(_space(1.0, 1.0e5), sweep_points=0)
        history = _run(adapter)
        expected = 2 + math.ceil(math.log2(5.0 / LOG10_ONE_PERCENT))
        assert len(history) <= expected + 1


class TestRefusal:
    def test_a_bracket_without_a_sign_change_raises(self) -> None:
        adapter = BisectionAdapter(_space(1.0, 10.0), sweep_points=3, bracket_expand=0)
        with pytest.raises(OptimizerError, match="keeps the same sign"):
            # The root sits far above the interval, so every residual is positive.
            _run(adapter, root=1.0e9)

    def test_a_trial_without_the_signed_component_is_refused(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=0)
        suggestion = adapter.ask(n=1)[0]
        blind = result_of(suggestion, 1.0, components={"rmse": 1.0})
        with pytest.raises(ObjectiveError, match="published no 'J_signed'"):
            adapter.tell([blind])

    def test_the_targets_are_decided_once_by_the_first_trial_that_scored(self) -> None:
        adapter = BisectionAdapter(_space(), sweep_points=3)
        scored_at, lost_at, later_at = adapter.ask(n=3)
        lost = result_of(lost_at, math.nan, status="failed")
        scored = result_of(scored_at, 1.0, components={"J_signed": 1.0})
        # Two bounds only now: the targets fixed by the trial before stay.
        later = {
            "J_signed": -1.0,
            BOUNDS_COMPONENT: 2.0,
            "weight_minimal": 1.0,
            "weight_maximal": 1.0,
        }

        adapter.tell([lost, scored, result_of(later_at, 1.0, components=later)])

        assert adapter._targets == (RootTarget("J_signed"),)
        assert sorted(adapter._residuals) == [1, 3]


class TestSignedComponentLookup:
    def test_a_bare_key_is_found(self) -> None:
        assert signed_residual({"J_signed": -2.0}) == -2.0

    def test_two_candidates_are_an_error(self) -> None:
        with pytest.raises(OptimizerError, match="several outputs"):
            signed_residual({"a.J_signed": 1.0, "b.J_signed": 2.0})


class TestTransform:
    """The whole search walks a log10 variable, so it must be given one."""

    def test_a_logit_transform_parameter_is_refused(self) -> None:
        space = ParameterSpace(
            [CalibParameter(name="Sy", lower=0.01, upper=0.3, search_space="logit")]
        )
        with pytest.raises(OptimizerError, match="logit"):
            BisectionAdapter(space)

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


def test_nothing_evaluated_means_nothing_to_report() -> None:
    adapter = BisectionAdapter(_space(upper=1.0e3), sweep_points=3, bracket_expand=0)
    assert adapter.best() is None
    assert adapter.root_interval(margin=1.0, kind="absolute") is None


def test_the_width_of_a_root_stops_at_a_trial_that_did_not_solve() -> None:
    # J = log10(K) - 2.5, and the top of the sweep at K = 1e4 does not solve.
    adapter = BisectionAdapter(_space(1.0, 1.0e4), sweep_points=5)
    while not adapter._done:
        (sugg,) = adapter.ask(1)
        residual = math.log10(float(sugg.values["K"])) - 2.5
        status = "infeasible" if residual > 1.0 else "completed"
        adapter.tell(
            [result_of(sugg, abs(residual), components={"net.J_signed": residual}, status=status)]
        )

    interval = adapter.root_interval(margin=1.0, kind="absolute")

    assert interval.lower == pytest.approx(10.0**1.5, rel=0.02)
    assert interval.upper == pytest.approx(1.0e3)
    assert (interval.lower_crossed, interval.upper_crossed) == (True, False)
    # K = 1 and K = 10 solved above the margin; K = 1e4 did not solve.
    assert interval.n_trials == interval.n_within + 2


def _converged_search() -> BisectionAdapter:
    """A one-root search on J = log10(K) - 2.5, closed, with every trial solved."""
    adapter = BisectionAdapter(_space(1.0, 1.0e4), sweep_points=5)
    while not adapter._done:
        (sugg,) = adapter.ask(1)
        residual = math.log10(float(sugg.values["K"])) - 2.5
        adapter.tell([result_of(sugg, abs(residual), components={"net.J_signed": residual})])
    return adapter


def _with_a_trial_asked_again(adapter, position: int, x: float, cost, status: str):
    """A copy of a closed search, with one more trial at ``x`` placed at ``position``."""
    again = copy.deepcopy(adapter)
    trial_id = max(again._points) + 1
    again._points[trial_id] = x
    extra = EvaluationResult(trial_id=trial_id, sim_id=None, cost=cost, status=status)
    again._history = [*again._history[:position], extra, *again._history[position:]]
    return again


@pytest.mark.parametrize(
    ("below_the_root", "cost", "status"),
    [
        # A cut point that failed, then solved when asked again, above the root.
        (False, math.inf, "infeasible"),
        # The same below the root, and with a cost that is not finite.
        (True, math.nan, "completed"),
    ],
)
def test_a_failed_trial_asked_again_and_solved_reads_like_the_solved_one(
    below_the_root, cost, status
) -> None:
    adapter = _converged_search()
    expected = adapter.root_interval(margin=0.5, kind="absolute").to_dict()
    root = adapter._points[adapter.best().trial_id]
    candidates = [x for x in adapter._points.values() if (x < root) is below_the_root]
    x = min(candidates, key=lambda value: abs(value - root))

    for position in range(len(adapter._history) + 1):
        again = _with_a_trial_asked_again(adapter, position, x, cost, status)

        assert again.root_interval(margin=0.5, kind="absolute").to_dict() == expected


def test_a_point_solved_twice_keeps_its_first_cost() -> None:
    adapter = _converged_search()
    expected = adapter.root_interval(margin=1.0, kind="absolute").to_dict()
    # K = 1e3 costs 0.5, under the margin. A later cost of 1e6 there would cross it.
    x = min(adapter._points.values(), key=lambda value: abs(value - 3.0))

    again = _with_a_trial_asked_again(adapter, len(adapter._history), x, 1.0e6, "completed")

    assert again.root_interval(margin=1.0, kind="absolute").to_dict() == expected


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


def test_a_count_of_three_roots_is_refused() -> None:
    with pytest.raises(OptimizerError, match="one or two roots"):
        root_search_budget(*NANCON_BOUNDS, roots=3)
    with pytest.raises(OptimizerError, match="one or two roots"):
        BisectionAdapter(_space(*NANCON_BOUNDS), roots=0)


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


def test_a_budget_counted_for_one_root_says_so_and_still_converges(caplog) -> None:
    adapter = BisectionAdapter(_space(*NANCON_BOUNDS), rel_tol=REL_TOL)
    with caplog.at_level(logging.WARNING):
        session = _run__root_search_closes(adapter, _two_bounds(), max_trials=40)

    assert "counted for 1 root(s) and the outputs score 2" in caplog.text
    assert session.converged
    assert adapter.roots == 2


# --------------------------------------------------------------------------- #
# One bound keeps today's search exactly
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# The report
# --------------------------------------------------------------------------- #
def test_the_report_publishes_the_roots_and_no_single_bracket() -> None:
    adapter = _two_root_adapter()
    session = _run__root_search_closes(adapter, _two_bounds())

    extra = search_outcome_extra(session)

    assert "bracket" not in extra
    assert extra["roots"] == adapter.roots_record()
    assert extra["search"]["converged"] is True
    assert extra["search"]["n_evaluations"] == 24


def test_no_interval_of_trials_is_put_around_a_value_between_two_roots() -> None:
    two = _two_root_adapter()
    one = BisectionAdapter(_space(*NANCON_BOUNDS), rel_tol=REL_TOL)

    assert closes_two_roots(_run__root_search_closes(two, _two_bounds())) is True
    assert closes_two_roots(_run__root_search_closes(one, _one_bound())) is False


class _Output:
    support = "network"
    verdict = SimpleNamespace(on_invalid="warn")


def test_eq4_is_read_on_each_bound_in_the_cost() -> None:
    adapter = _two_root_adapter()
    session = _run__root_search_closes(adapter, _two_bounds())

    extra = r_optim_verdict_extra({"net": _Output()}, session.best.components)

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

    verdicts = r_optim_verdict_extra({"net": _Output()}, components)["r_optim_verdict"]

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
map.complete = "complete.gpkg"
{minimal}
{extent}

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""

_EXTENT = "[calibration.outputs.net.model.extent]"
_SHARES = "{ permanent = 0.5, complete = 0.5 }"


def _load(
    tmp_path: Path,
    *,
    max_trials: int = 20,
    minimal: bool = True,
    extent: str = _EXTENT,
    role: str | None = None,
):
    path = tmp_path / "calibration.toml"
    role = role or (_SHARES if extent else '"permanent"')
    maps = f'map.permanent = "permanent.gpkg"\nmap.calibrate_on = {role}' if minimal else ""
    text = _TOML.format(max_trials=max_trials, minimal=maps, extent=extent)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    for name in ("complete.gpkg", "permanent.gpkg"):
        (tmp_path / name).write_bytes(b"")
    cfg, _raw = load_toml_calibration(path)
    return cfg


@pytest.mark.parametrize(
    ("minimal", "extent", "role"),
    [
        (False, _EXTENT, None),
        (True, "", None),
        (True, _EXTENT, '"permanent"'),
        (True, _EXTENT, '"complete"'),
    ],
)
def test_anything_short_of_two_weighted_bounds_is_one_root(
    tmp_path: Path, minimal: bool, extent: str, role: str | None
) -> None:
    cfg = _load(tmp_path, minimal=minimal, extent=extent, role=role)

    assert _engine_kwargs(cfg, _space(*NANCON_BOUNDS), start_at=None)["roots"] == 1


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
map.complete = "complete.gpkg"
map.permanent = "permanent.gpkg"
map.calibrate_on = {{ permanent = 0.5, complete = 0.5 }}

[calibration.outputs.net.model.extent]
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


# --------------------------------------------------------------------------- #
# The sweep is handed out whole, in order
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Every width closes a bracket around the root the binary search closes
# --------------------------------------------------------------------------- #
ONE_ROOT_ROUNDS = {1: (15, 15), 2: (9, 16), 4: (6, 20), 7: (4, 23)}

TWO_ROOT_ROUNDS = {1: (24, 24), 2: (13, 24), 4: (8, 26), 7: (6, 31)}


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
map.complete = "complete.gpkg"
map.permanent = "permanent.gpkg"
map.calibrate_on = {{ permanent = 0.5, complete = 0.5 }}

[calibration.outputs.net.model.extent]

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


# --------------------------------------------------------------------------- #
# What the adapter refuses, and what it says before it has a root
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"rel_tol": 0.0}, "rel_tol must be strictly positive, got 0.0"),
        ({"sweep_points": -1}, "sweep_points must be positive or zero, got -1"),
    ],
)
def test_a_tolerance_or_a_sweep_that_cannot_be_walked_is_refused(kwargs, match) -> None:
    with pytest.raises(OptimizerError, match=match):
        BisectionAdapter(_space(), **kwargs)


@pytest.mark.parametrize(
    ("components", "match"),
    [
        ({"net.n_bounds_scored": 2.0}, "publishes no 'weight_minimal'"),
        (
            {"net.n_bounds_scored": 2.0, "net.weight_minimal": 0.0, "net.weight_maximal": 0.0},
            "weighs both of its bounds zero",
        ),
        ({}, "published no 'J_signed' component"),
    ],
)
def test_a_first_trial_that_cannot_say_which_roots_to_close_is_refused(components, match) -> None:
    adapter = _two_root_adapter()
    (first,) = adapter.ask(1)

    with pytest.raises(ObjectiveError, match=match):
        adapter.tell([result_of(first, 1.0, components=components)])


def test_a_first_batch_that_failed_without_a_residual_ends_in_a_refusal() -> None:
    adapter = _two_root_adapter()
    failed = [
        EvaluationResult(trial_id=s.trial_id, sim_id=None, cost=1e9, status="failed")
        for s in adapter.ask(100)
    ]

    with pytest.raises(OptimizerError, match="no usable residual"):
        adapter.tell(failed)


def test_before_any_root_the_adapter_has_no_bracket_no_record_and_no_place_for_a_trial() -> None:
    adapter = _two_root_adapter()
    (first,) = adapter.ask(1)
    adapter.tell([_two_bounds()(first)])

    assert adapter.brackets == {}
    assert adapter.roots_record() is None
    assert math.isnan(adapter._physical_of(None))
    assert not adapter._inside(999, (0.0, 1.0))


def test_a_spent_search_has_nothing_to_suggest() -> None:
    adapter = BisectionAdapter(_space(), sweep_points=0)
    adapter._done = True

    with pytest.raises(OptimizerError, match="nothing left to suggest"):
        adapter.suggest_next()


def test_the_first_suggestion_is_the_first_point_of_the_sweep() -> None:
    suggestion = BisectionAdapter(_space(), sweep_points=3).suggest_next()

    assert suggestion.trial_id == 1
    assert suggestion.values["K"] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("bracket", "points", "winner", "inside"),
    [
        # Tied residual-free trials: the nearest to the middle (5) wins.
        ((0.0, 10.0), {1: 1.0, 2: 9.0, 3: 6.5}, 3, True),
        # Every trial lies outside; one has no recorded point and counts as the middle.
        ((0.0, 1.0), {1: 3.0, 2: 9.0}, 3, False),
    ],
)
def test_a_tie_goes_to_the_trial_nearest_the_middle_of_the_bracket(
    bracket, points, winner, inside, caplog
) -> None:
    adapter = BisectionAdapter(_space())
    adapter._targets = (SimpleNamespace(component="c"),)
    adapter._brackets = {"c": bracket}
    adapter._points = points
    valid = [
        EvaluationResult(trial_id=i, sim_id=None, cost=1.0, status="completed") for i in (1, 2, 3)
    ]

    with caplog.at_level(logging.WARNING):
        assert adapter._pick(valid).trial_id == winner

    assert ("No completed trial lies inside" in caplog.text) is not inside
    assert ("of K:" in caplog.text) is not inside
