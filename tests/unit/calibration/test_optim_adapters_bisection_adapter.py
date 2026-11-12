"""One-dimensional root search (`optim.adapters.bisection_adapter`).
The residual is a signed gap (percent) that crosses zero at a known K (m/s),
searched on a log scale inside a bracket. With two network bounds it closes
one root per bound, then solves their weighted geometric mean once.
"""

from __future__ import annotations

import copy
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

BOUNDS = (1e-7, 1e-3)  # K bounds of the Nancon, m/s
ROOT_K = 600.0  # root of the staircase on a wide K range
ROOT_MIN = 3.0e-6  # root of the minimal (permanent) map, m/s
ROOT_MAX = 2.0e-4  # root of the maximal (complete) map, m/s
REL_TOL = 0.01
TOL = math.log10(1.0 + REL_TOL)  # decades

# A residual that is exactly 2.913 m within PLATEAU decades of ROOT.
ROOT = 2.09e-4
PLATEAU = 0.05

# The sweep of 3 points from 1e-7 to 1e-3 has intervals of 2/3 decade.
SWEEP_LOW = -5.0
SWEEP_STEP = 2.0 / 3.0
# Three zero crossings inside the first sweep interval.
WIGGLE = tuple(SWEEP_LOW + fraction * SWEEP_STEP for fraction in (0.1, 0.3, 0.85))

Residual = Callable[[float], float]


def log_space(lower: float = 1.0, upper: float = 1.0e5, name: str = "K") -> ParameterSpace:
    return make_space((name, lower, upper, "log"))


def two_root_adapter(**kwargs) -> BisectionAdapter:
    return BisectionAdapter(log_space(*BOUNDS), rel_tol=REL_TOL, roots=2, **kwargs)


def search_adapter(**kwargs) -> BisectionAdapter:
    return BisectionAdapter(log_space(*BOUNDS), rel_tol=REL_TOL, **kwargs)


def staircase_evaluator(suggestion, *, root: float = ROOT_K) -> EvaluationResult:
    # A staircase that never lands on zero. The real criterion is a step
    # function that jumps over its root, so a search leaning on a smooth
    # residual would pass here and fail on a catchment.
    value = float(next(iter(suggestion.values.values())))
    residual = staircase(root, value)
    return result_of(
        suggestion, abs(residual), components={"net.J_signed": residual, "net.J": abs(residual)}
    )


def run_asking_one(adapter, *, max_trials: int = 40, **kwargs) -> list[EvaluationResult]:
    """Drive the adapter the way the engine does, one point per ask."""
    history: list[EvaluationResult] = []
    while len(history) < max_trials:
        suggestions = adapter.ask(n=1)
        if not suggestions:
            break
        results = [staircase_evaluator(sugg, **kwargs) for sugg in suggestions]
        history.extend(results)
        adapter.tell(results)
        if adapter.converged():
            break
    return history


def run_to_end(adapter: BisectionAdapter, evaluator, max_trials: int | str = AUTO_BUDGET):
    return run_engine(adapter.space, adapter, evaluator, max_trials)


def two_bounds(
    *,
    root_min: float = ROOT_MIN,
    root_max: float = ROOT_MAX,
    weights: tuple[float, float] = (0.5, 0.5),
    fail: set[int] | None = None,
    seen: list[ParamSuggestion] | None = None,
):
    """Score a trial the way a network output with two bounds publishes it.

    The minimal (permanent) map needs more water than the maximal one, so its
    root sits at a lower K. A trial id in `fail` comes back failed.
    """
    w_min, w_max = weights

    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        if seen is not None:
            seen.append(sugg)
        if fail and sugg.trial_id in fail:
            return EvaluationResult(trial_id=sugg.trial_id, sim_id=None, cost=1e9, status="failed")
        value = float(sugg.values["K"])
        j_min = staircase(root_min, value, 200.0)
        j_max = staircase(root_max, value, 200.0)
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


def one_bound(root: float = ROOT_MAX):
    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        residual = staircase(root, float(sugg.values["K"]), 200.0)
        components = {
            "net.J_signed": residual,
            "net.J_signed_maximal": residual,
            "net.n_bounds_scored": 1.0,
        }
        return result_of(sugg, abs(residual), components=components)

    return evaluate


def smooth(root: float) -> Residual:
    return lambda value: math.log10(root) - math.log10(value)


def step(root: float) -> Residual:
    return lambda value: staircase(root, value, 200.0)


def wiggle(first: float, second: float, third: float) -> Residual:
    """Positive below `first`, negative up to `second`, positive up to `third`, then negative."""

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


def one_residual(residual: Residual):
    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        value = residual(float(sugg.values["K"]))
        return result_of(sugg, abs(value), components={"net.J_signed": value})

    return evaluate


def two_residuals(minimal: Residual, maximal: Residual):
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


def plateau_evaluator(sugg: ParamSuggestion) -> EvaluationResult:
    gap = math.log10(ROOT) - math.log10(float(sugg.values["K"]))
    magnitude = 2.913 + 1000.0 * max(0.0, abs(gap) - PLATEAU)
    residual = math.copysign(magnitude, gap)
    return result_of(sugg, abs(residual), components={"net.J_signed": residual})


# (adapter options, evaluator). The wiggle has three crossings in one sweep interval.
SCENARIOS = {
    "one_expanded": ({}, one_residual(step(3e-2))),
    "one_wiggle": ({}, one_residual(wiggle(*WIGGLE))),
    "one_step": ({}, one_residual(step(ROOT))),
    "two_step": ({"roots": 2}, two_residuals(step(ROOT_MIN), step(ROOT_MAX))),
    "two_expanded": ({"roots": 2}, two_residuals(step(3e-9), step(ROOT_MAX))),
}


def cut_search(adapter: BisectionAdapter, evaluate, width: int) -> list[list[ParamSuggestion]]:
    """Ask `width` points, evaluate, tell, until the search stops. Return each round."""
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


def log_k(sugg: ParamSuggestion) -> float:
    return math.log10(float(sugg.values["K"]))


def returned_decades(adapter: BisectionAdapter, rounds: list[list[ParamSuggestion]]) -> float:
    record = adapter.roots_record()
    if record is not None:
        return math.log10(record["value"])
    best = adapter.best().trial_id
    return next(log_k(sugg) for batch in rounds for sugg in batch if sugg.trial_id == best)


def contains(bracket: tuple[float, float], x: float) -> bool:
    low, high = bracket
    return low - 1e-12 <= x <= high + 1e-12


def solved_log_search() -> BisectionAdapter:
    """A one-root search on J = log10(K) - 2.5, closed, with every trial solved."""
    adapter = BisectionAdapter(log_space(1.0, 1.0e4), sweep_points=5)
    while not adapter._done:
        (sugg,) = adapter.ask(1)
        residual = math.log10(float(sugg.values["K"])) - 2.5
        adapter.tell([result_of(sugg, abs(residual), components={"net.J_signed": residual})])
    return adapter


def with_trial_asked_again(adapter, position: int, x: float, cost, status: str):
    """A copy of a closed search with one more trial at `x`, placed at `position`."""
    again = copy.deepcopy(adapter)
    trial_id = max(again._points) + 1
    again._points[trial_id] = x
    extra = EvaluationResult(trial_id=trial_id, sim_id=None, cost=cost, status=status)
    again._history = [*again._history[:position], extra, *again._history[position:]]
    return again


CONFIG_TOML = """
[calibration]
method = "bisection"
max_trials = 20

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
EXTENT = "[calibration.outputs.net.model.extent]"
SHARES = "{ permanent = 0.5, complete = 0.5 }"


def load_config(tmp_path: Path, *, minimal: bool = True, extent: str = EXTENT, role=None):
    role = role or (SHARES if extent else '"permanent"')
    maps = f'map.permanent = "permanent.gpkg"\nmap.calibrate_on = {role}' if minimal else ""
    path = tmp_path / "calibration.toml"
    path.write_text(textwrap.dedent(CONFIG_TOML.format(minimal=maps, extent=extent)), "utf-8")
    for name in ("complete.gpkg", "permanent.gpkg"):
        (tmp_path / name).write_bytes(b"")
    cfg, _raw = load_toml_calibration(path)
    return cfg


class NetworkOutput:
    support = "network"
    verdict = SimpleNamespace(on_invalid="warn")


def test_budget_matches_arithmetic():
    # Five decades to close to one per cent: two ends plus ceil(log2(5 / log10(1.01))) halvings.
    history = run_asking_one(BisectionAdapter(log_space(1.0, 1.0e5), sweep_points=0))

    assert len(history) <= 2 + math.ceil(math.log2(5.0 / LOG10_ONE_PERCENT)) + 1


def test_bracket_without_sign_change():
    adapter = BisectionAdapter(log_space(1.0, 10.0), sweep_points=3, bracket_expand=0)

    with pytest.raises(OptimizerError, match="keeps the same sign"):
        # The root sits far above the interval, so every residual is positive.
        run_asking_one(adapter, root=1.0e9)


def test_signed_residual_lookup():
    assert signed_residual({"J_signed": -2.0}) == -2.0
    with pytest.raises(OptimizerError, match="several outputs"):
        signed_residual({"a.J_signed": 1.0, "b.J_signed": 2.0})


def test_targets_fixed_by_first_scored_trial():
    adapter = BisectionAdapter(log_space(), sweep_points=3)
    scored_at, lost_at, later_at = adapter.ask(n=3)
    lost = result_of(lost_at, math.nan, status="failed")
    scored = result_of(scored_at, 1.0, components={"J_signed": 1.0})
    # Two bounds only now, and the targets fixed by the trial before stay.
    later = {"J_signed": -1.0, BOUNDS_COMPONENT: 2.0, "weight_minimal": 1.0, "weight_maximal": 1.0}

    adapter.tell([lost, scored, result_of(later_at, 1.0, components=later)])

    assert adapter._targets == (RootTarget("J_signed"),)
    assert sorted(adapter._residuals) == [1, 3]


def test_empty_search_reports_nothing():
    adapter = BisectionAdapter(log_space(upper=1.0e3), sweep_points=3, bracket_expand=0)

    assert adapter.best() is None
    assert adapter.root_interval(margin=1.0, kind="absolute") is None


def test_interval_stops_at_unsolved_trial():
    # J = log10(K) - 2.5, and the top of the sweep at K = 1e4 does not solve.
    adapter = BisectionAdapter(log_space(1.0, 1.0e4), sweep_points=5)
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
    # K = 1 and K = 10 solved above the margin, K = 1e4 did not solve.
    assert interval.n_trials == interval.n_within + 2


# (point is below the root, cost of the repeated trial, its status)
REPEATED_FAILURES = [
    pytest.param(False, math.inf, "infeasible", id="cut point failed above the root"),
    pytest.param(True, math.nan, "completed", id="nan cost below the root"),
]


@pytest.mark.parametrize(("below_the_root", "cost", "status"), REPEATED_FAILURES)
def test_failed_repeat_changes_nothing(below_the_root, cost, status):
    adapter = solved_log_search()
    expected = adapter.root_interval(margin=0.5, kind="absolute").to_dict()
    root = adapter._points[adapter.best().trial_id]
    candidates = [x for x in adapter._points.values() if (x < root) is below_the_root]
    x = min(candidates, key=lambda value: abs(value - root))

    for position in range(len(adapter._history) + 1):
        again = with_trial_asked_again(adapter, position, x, cost, status)

        assert again.root_interval(margin=0.5, kind="absolute").to_dict() == expected


def test_repeated_point_keeps_first_cost():
    adapter = solved_log_search()
    expected = adapter.root_interval(margin=1.0, kind="absolute").to_dict()
    # K = 1e3 costs 0.5, under the margin. A later cost of 1e6 there would cross it.
    x = min(adapter._points.values(), key=lambda value: abs(value - 3.0))

    again = with_trial_asked_again(adapter, len(adapter._history), x, 1.0e6, "completed")

    assert again.root_interval(margin=1.0, kind="absolute").to_dict() == expected


def test_answer_outside_bracket_warns(caplog):
    adapter = BisectionAdapter(log_space(*BOUNDS), rel_tol=REL_TOL, sweep_points=3)
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

    assert winner.trial_id == 1
    assert "No completed trial lies inside the final bracket" in caplog.text


def test_no_bracket_returns_lowest_cost():
    adapter = BisectionAdapter(log_space(*BOUNDS), rel_tol=REL_TOL, sweep_points=3)
    (suggestion,) = adapter.ask(1)
    result = plateau_evaluator(suggestion)
    adapter.tell([result])

    assert adapter.bracket is None
    assert adapter.best() is result
    assert adapter.bracket_record() is None


# (bracket, log10 K of each trial, winner, a trial lies inside the bracket)
TIES = [
    # Tied residual-free trials, and the nearest to the middle (5) wins.
    pytest.param((0.0, 10.0), {1: 1.0, 2: 9.0, 3: 6.5}, 3, True, id="inside"),
    # Every trial lies outside, and trial 3 has no recorded point so it counts as the middle.
    pytest.param((0.0, 1.0), {1: 3.0, 2: 9.0}, 3, False, id="outside"),
]


@pytest.mark.parametrize(("bracket", "points", "winner", "inside"), TIES)
def test_tie_goes_to_trial_nearest_middle(bracket, points, winner, inside, caplog):
    adapter = BisectionAdapter(log_space())
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


def test_value_is_weighted_mean_of_roots():
    seen: list[ParamSuggestion] = []
    adapter = two_root_adapter()
    session = run_to_end(adapter, two_bounds(seen=seen))
    record = adapter.roots_record()
    best = session.best

    expected = 10.0 ** (
        0.5 * math.log10(record["minimal"]["k_star"])
        + 0.5 * math.log10(record["maximal"]["k_star"])
    )
    assert best.trial_id == record["combined_trial_id"] == seen[-1].trial_id
    assert seen[-1].source == "combined"
    assert float(seen[-1].values["K"]) == pytest.approx(expected, rel=1e-12)
    assert record["value"] == pytest.approx(expected, rel=1e-12)
    assert math.isclose(expected, math.sqrt(ROOT_MIN * ROOT_MAX), rel_tol=2 * REL_TOL)
    # Every number beside the value comes from that solve. Above the minimal
    # root and below the maximal one, each residual has its own sign.
    assert best.components["net.J_signed_minimal"] < 0.0 < best.components["net.J_signed_maximal"]


def test_record_publishes_both_roots():
    adapter = two_root_adapter()
    run_to_end(adapter, two_bounds())
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


def test_weights_move_the_value():
    adapter = two_root_adapter()
    session = run_to_end(adapter, two_bounds(weights=(0.25, 0.75)))
    record = adapter.roots_record()

    expected = 10.0 ** (
        0.25 * math.log10(record["minimal"]["k_star"])
        + 0.75 * math.log10(record["maximal"]["k_star"])
    )
    assert session.best is not None
    assert record["value"] == pytest.approx(expected, rel=1e-12)
    assert record["minimal"]["weight"] == 0.25


def test_zero_weight_bound_not_searched():
    # The maximal root lies far outside every expansion, so searching it would refuse.
    seen: list[ParamSuggestion] = []
    adapter = BisectionAdapter(log_space(*BOUNDS), rel_tol=REL_TOL, bracket_expand=0)
    session = run_to_end(adapter, two_bounds(root_max=1e3, weights=(1.0, 0.0), seen=seen))

    assert session.converged
    assert adapter.roots == 1
    assert adapter.roots_record() is None
    assert all(sugg.source != "combined" for sugg in seen)
    assert float(session.best.components["net.J_signed_minimal"]) == pytest.approx(0.0, abs=0.01)
    low, high = adapter.bracket
    assert 10.0**low <= ROOT_MIN <= 10.0**high


def test_bound_without_sign_change_named():
    adapter = BisectionAdapter(log_space(*BOUNDS), rel_tol=REL_TOL, roots=2, bracket_expand=1)

    with pytest.raises(OptimizerError, match="maximal bound.*J_signed_maximal"):
        run_to_end(adapter, two_bounds(root_max=1e3))


def test_unsolved_combined_value_not_converged():
    budget = root_search_budget(*BOUNDS, roots=2).nominal
    adapter = two_root_adapter()
    session = run_to_end(adapter, two_bounds(fail={budget}))

    assert not session.converged
    assert adapter.roots_record()["combined_trial_id"] is None
    assert adapter.roots_record()["value"] is None
    # What stands in is a trial that solved, never the unsolved combined value.
    assert session.best.status == "completed"


# (root of the minimal map, root of the maximal map), both found after expansions of the bracket
EXPANDED_ROOTS = [(3e-9, 2e-4), (3e-9, 3e-2), (2e-4, 3e-1)]


@pytest.mark.parametrize(("root_min", "root_max"), EXPANDED_ROOTS)
def test_auto_budget_covers_expansions(root_min, root_max):
    adapter = two_root_adapter()
    session = run_to_end(adapter, two_bounds(root_min=root_min, root_max=root_max))

    assert session.converged
    assert session.extension == 0
    assert len(session.history) <= adapter.counted_budget.worst
    record = adapter.roots_record()
    assert record["minimal"]["k_star"] == pytest.approx(root_min, rel=REL_TOL)
    assert record["maximal"]["k_star"] == pytest.approx(root_max, rel=REL_TOL)


def test_one_root_budget_warns_and_converges(caplog):
    adapter = search_adapter()
    with caplog.at_level(logging.WARNING):
        session = run_to_end(adapter, two_bounds(), max_trials=40)

    assert "counted for 1 root(s) and the outputs score 2" in caplog.text
    assert session.converged
    assert adapter.roots == 2


def test_report_publishes_roots_not_bracket():
    adapter = two_root_adapter()
    session = run_to_end(adapter, two_bounds())

    extra = search_outcome_extra(session)

    assert "bracket" not in extra
    assert extra["roots"] == adapter.roots_record()
    assert extra["search"]["converged"] is True
    assert extra["search"]["n_evaluations"] == 24


def test_interval_only_around_one_root():
    two = two_root_adapter()
    one = search_adapter()

    assert closes_two_roots(run_to_end(two, two_bounds())) is True
    assert closes_two_roots(run_to_end(one, one_bound())) is False


def test_r_optim_verdict_per_bound():
    session = run_to_end(two_root_adapter(), two_bounds())

    verdicts = r_optim_verdict_extra({"net": NetworkOutput()}, session.best.components)[
        "r_optim_verdict"
    ]

    assert set(verdicts) == {"net_minimal", "net_maximal"}
    assert verdicts["net_minimal"]["valid"] is True
    assert verdicts["net_minimal"]["D_optim"] == 75.0
    assert verdicts["net_maximal"]["valid"] is False
    assert verdicts["net_maximal"]["value"] == 2.5
    # Each bound is read against the length its own map resolved.
    assert verdicts["net_minimal"]["validity_length_m"] == 100.0
    assert verdicts["net_maximal"]["validity_length_m"] == 110.0
    assert verdicts["net_maximal"]["provenance"] == "declared_accuracy"


def test_r_optim_verdict_skips_zero_weight():
    suggestion = ParamSuggestion(trial_id=1, values={"K": 1e-5})
    components = dict(two_bounds(weights=(1.0, 0.0))(suggestion).components)

    verdicts = r_optim_verdict_extra({"net": NetworkOutput()}, components)["r_optim_verdict"]

    assert set(verdicts) == {"net_minimal"}


# (minimal map given, extent section, calibrate_on)
SINGLE_ROOT_CONFIGS = [
    pytest.param(False, EXTENT, None, id="no minimal map"),
    pytest.param(True, "", None, id="no extent"),
    pytest.param(True, EXTENT, '"permanent"', id="calibrated on permanent"),
    pytest.param(True, EXTENT, '"complete"', id="calibrated on complete"),
]


@pytest.mark.parametrize(("minimal", "extent", "role"), SINGLE_ROOT_CONFIGS)
def test_config_gives_one_root(tmp_path, minimal, extent, role):
    cfg = load_config(tmp_path, minimal=minimal, extent=extent, role=role)

    assert _engine_kwargs(cfg, log_space(*BOUNDS), start_at=None)["roots"] == 1


@pytest.mark.parametrize("width", [1, 2, 4, 7])
@pytest.mark.parametrize("name", ["one_expanded", "two_expanded"])
def test_expanded_root_within_budget(name, width):
    options, evaluate = SCENARIOS[name]
    binary = search_adapter(**options)
    binary_rounds = cut_search(binary, evaluate, 1)
    adapter = search_adapter(**options)

    rounds = cut_search(adapter, evaluate, width)

    assert adapter.converged()
    assert sum(len(batch) for batch in rounds) <= adapter.counted_budget.worst
    assert (
        abs(returned_decades(adapter, rounds) - returned_decades(binary, binary_rounds)) <= 2 * TOL
    )


@pytest.mark.parametrize("width", [1, 2, 3, 5, 7])
def test_wiggle_keeps_binary_crossing(width):
    # Binary bisection finds the midpoint positive, keeps the upper half, then
    # the upper quarter, and closes on the third crossing. Cut into 4, 6 or 8
    # parts, the round holds that midpoint, and its halvings are followed.
    options, evaluate = SCENARIOS["one_wiggle"]
    adapter = search_adapter(**options)

    cut_search(adapter, evaluate, width)

    assert adapter.converged()
    assert contains(adapter.bracket, WIGGLE[2])


def test_first_round_in_four_parts():
    options, evaluate = SCENARIOS["one_wiggle"]
    adapter = search_adapter(**options)
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


def test_round_without_midpoint_keeps_lowest(caplog):
    # Cut into five parts, the round holds no midpoint. Nothing says which half
    # binary bisection would keep, so the lowest crossing is kept, as the sweep
    # keeps the first of its crossings. The warning says the root is not unique.
    options, evaluate = SCENARIOS["one_wiggle"]
    adapter = search_adapter(**options)

    with caplog.at_level(logging.WARNING):
        cut_search(adapter, evaluate, 4)

    assert adapter.converged()
    assert contains(adapter.bracket, WIGGLE[0])
    assert "changes sign 3 times" in caplog.text


def test_shared_bracket_cut_once():
    # Both roots lie in one sweep interval, so the round cuts it into five
    # parts once, instead of proposing two cuts twice.
    evaluate = two_residuals(step(1.5e-4), step(ROOT_MAX))
    adapter = two_root_adapter()

    rounds = cut_search(adapter, evaluate, 4)

    first_cut = rounds[2]
    low, high = -4.0 - 1.0 / 3.0, -3.0 - 2.0 / 3.0
    assert [sugg.source for sugg in first_cut] == ["bisect"] * 4
    assert [log_k(sugg) for sugg in first_cut] == pytest.approx(
        [low + (high - low) * index / 5.0 for index in range(1, 5)], abs=1e-12
    )
    assert adapter.converged()
    assert contains(adapter.brackets["minimal"], math.log10(1.5e-4))
    assert contains(adapter.brackets["maximal"], math.log10(ROOT_MAX))
    assert adapter.roots_record()["closed"] is True


# (scenario, points per ask)
SPENT_EVALUATIONS = [
    pytest.param("one_step", 4, id="one root, 4 points"),
    pytest.param("two_step", 4, id="two roots, 4 points"),
    pytest.param("two_step", 7, id="two roots, 7 points"),
]


@pytest.mark.parametrize(("name", "width"), SPENT_EVALUATIONS)
def test_evaluations_left_follow_spent(name, width):
    options, evaluate = SCENARIOS[name]
    adapter = search_adapter(**options)
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


def test_first_trial_without_residual_refused():
    adapter = two_root_adapter()
    failed = [
        EvaluationResult(trial_id=s.trial_id, sim_id=None, cost=1e9, status="failed")
        for s in adapter.ask(100)
    ]

    with pytest.raises(OptimizerError, match="no usable residual"):
        adapter.tell(failed)


def test_trial_without_signed_component_refused():
    adapter = BisectionAdapter(log_space(), sweep_points=0)
    suggestion = adapter.ask(n=1)[0]

    with pytest.raises(ObjectiveError, match="published no 'J_signed'"):
        adapter.tell([result_of(suggestion, 1.0, components={"rmse": 1.0})])


def test_state_before_any_root():
    adapter = two_root_adapter()
    (first,) = adapter.ask(1)
    adapter.tell([two_bounds()(first)])

    assert adapter.brackets == {}
    assert adapter.roots_record() is None
    assert math.isnan(adapter._physical_of(None))
    assert not adapter._inside(999, (0.0, 1.0))


def test_spent_search_has_nothing_to_suggest():
    adapter = BisectionAdapter(log_space(), sweep_points=0)
    adapter._done = True

    with pytest.raises(OptimizerError, match="nothing left to suggest"):
        adapter.suggest_next()


def test_first_suggestion_is_sweep_start():
    suggestion = BisectionAdapter(log_space(), sweep_points=3).suggest_next()

    assert suggestion.trial_id == 1
    assert suggestion.values["K"] == pytest.approx(1.0)


def two_parameter_space() -> ParameterSpace:
    return ParameterSpace(
        [
            CalibParameter(name="K", lower=1.0, upper=10.0),
            CalibParameter(name="Sy", lower=0.01, upper=0.3),
        ]
    )


def logit_space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="Sy", lower=0.01, upper=0.3, search_space="logit")])


def identity_space() -> ParameterSpace:
    return ParameterSpace([CalibParameter(name="K", lower=1.0e-9, upper=1.0e-3)])


# (space, adapter options, part of the message). The search walks a log10
# variable, so a space without one is refused.
ADAPTER_REFUSALS = [
    pytest.param(two_parameter_space(), {}, "searches one parameter", id="two parameters"),
    pytest.param(logit_space(), {}, "logit", id="logit space"),
    pytest.param(identity_space(), {"sweep_points": 7}, "log10 variable", id="identity space"),
    pytest.param(log_space(), {"roots": 0}, "one or two roots", id="zero roots"),
    pytest.param(log_space(*BOUNDS), {"batch": 0}, "at least one point", id="zero batch"),
    pytest.param(
        log_space(), {"rel_tol": 0.0}, "rel_tol must be strictly positive, got 0.0", id="rel_tol"
    ),
    pytest.param(
        log_space(),
        {"sweep_points": -1},
        "sweep_points must be positive or zero, got -1",
        id="sweep_points",
    ),
]


@pytest.mark.parametrize(("space", "options", "match"), ADAPTER_REFUSALS)
def test_adapter_refusals(space, options, match):
    with pytest.raises(OptimizerError, match=match):
        BisectionAdapter(space, **options)


BUDGET_REFUSALS = [
    pytest.param({"roots": 3}, "one or two roots", id="three roots"),
    pytest.param({"batch": 0}, "at least one point", id="zero batch"),
]


@pytest.mark.parametrize(("options", "match"), BUDGET_REFUSALS)
def test_budget_refusals(options, match):
    with pytest.raises(OptimizerError, match=match):
        root_search_budget(*BOUNDS, **options)


# (components of the first trial, part of the message)
FIRST_TRIAL_REFUSALS = [
    pytest.param({"net.n_bounds_scored": 2.0}, "publishes no 'weight_minimal'", id="no weight"),
    pytest.param(
        {"net.n_bounds_scored": 2.0, "net.weight_minimal": 0.0, "net.weight_maximal": 0.0},
        "weighs both of its bounds zero",
        id="both weights zero",
    ),
    pytest.param({}, "published no 'J_signed' component", id="no residual"),
]


@pytest.mark.parametrize(("components", "match"), FIRST_TRIAL_REFUSALS)
def test_first_trial_refusals(components, match):
    adapter = two_root_adapter()
    (first,) = adapter.ask(1)

    with pytest.raises(ObjectiveError, match=match):
        adapter.tell([result_of(first, 1.0, components=components)])
