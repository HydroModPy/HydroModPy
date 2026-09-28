"""A root search asked for several points cuts its bracket into that many parts.

One point per ask is the binary search, trial for trial: the recording in
``golden/root_search_width_one_golden.json`` holds the trials it asked before
it learnt to cut its bracket several points at a time. With ``n`` points per
ask the sweep comes ``n`` points at a time, each round cuts a bracket into
``n + 1`` equal parts, and two brackets share a round. The root then lies in
a bracket as narrow as the binary search's, found in far fewer rounds.

The residuals are synthetic: a smooth log-linear one, a staircase that steps
over zero without landing on it, as the criterion does on a catchment, and a
wiggle with three crossings inside one sweep interval.
"""

from __future__ import annotations

import json
import logging
import math
import textwrap
from collections.abc import Callable
from pathlib import Path

import pytest

from hydromodpy.calibration.optim.adapters.bisection_adapter import (
    BisectionAdapter,
    root_search_budget,
)
from hydromodpy.calibration.optim.engine import CalibrationEngine
from hydromodpy.calibration.optim.optimizer import (
    EvaluationResult,
    ParamSuggestion,
    engine_traits,
)
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.optim.stopping import AUTO_BUDGET
from hydromodpy.calibration.preflight import _check_the_budgets
from hydromodpy.calibration.runners.cli_runner import load_toml_calibration
from hydromodpy.core.exceptions import OptimizerError

GOLDEN = Path(__file__).parent / "golden" / "root_search_width_one_golden.json"

BOUNDS = (1e-7, 1e-3)
REL_TOL = 0.01
TOL = math.log10(1.0 + REL_TOL)
"""The stopping width, in decades."""
ROOT = 2.09e-4
ROOT_MIN = 3.0e-6
ROOT_MAX = 2.0e-4

WIDTHS = (1, 2, 4, 7)

SWEEP_LOW = -5.0
"""Lower end, in decades, of the sweep interval the wiggle crosses three times."""
SWEEP_STEP = 2.0 / 3.0
"""The sweep step on [1e-7, 1e-3] with seven points."""
WIGGLE = tuple(SWEEP_LOW + fraction * SWEEP_STEP for fraction in (0.1, 0.3, 0.85))
"""The three crossings of the wiggle, in decades."""

Residual = Callable[[float], float]


def _space() -> ParameterSpace:
    return ParameterSpace(
        [CalibParameter(name="K", lower=BOUNDS[0], upper=BOUNDS[1], transform="log")]
    )


def _smooth(root: float) -> Residual:
    return lambda value: math.log10(root) - math.log10(value)


def _step(root: float) -> Residual:
    return lambda value: (math.floor(math.log10(root / value) * 200.0) + 0.5) / 200.0


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
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=abs(value),
            status="completed",
            components={"net.J_signed": value},
        )

    return evaluate


def _two(minimal: Residual, maximal: Residual):
    def evaluate(sugg: ParamSuggestion) -> EvaluationResult:
        value = float(sugg.values["K"])
        j_min, j_max = minimal(value), maximal(value)
        return EvaluationResult(
            trial_id=sugg.trial_id,
            sim_id=None,
            objective_value=0.5 * abs(j_min) + 0.5 * abs(j_max),
            status="completed",
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
"""Each scenario of the recording: the adapter's options and its evaluator."""


def _close(adapter: BisectionAdapter, evaluate, width: int) -> list[list[ParamSuggestion]]:
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
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, **options)

    rounds = _close(adapter, evaluate, 1)

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
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, **options)

    rounds = _close(adapter, evaluate, width)
    sweep = [batch for batch in rounds if batch[0].source == "sweep"]

    assert [len(batch) for batch in sweep] == sizes
    assert [float(sugg.values["K"]) for batch in sweep for sugg in batch] == recorded


# --------------------------------------------------------------------------- #
# Every width closes a bracket around the root the binary search closes
# --------------------------------------------------------------------------- #

ONE_ROOT_ROUNDS = {1: (15, 15), 2: (9, 16), 4: (6, 20), 7: (4, 23)}
"""Rounds and evaluations of one root inside the Nancon bounds, per width."""

TWO_ROOT_ROUNDS = {1: (24, 24), 2: (13, 24), 4: (8, 26), 7: (6, 31)}
"""Rounds and evaluations of two roots inside the Nancon bounds, per width."""


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("shape", [_smooth, _step])
def test_one_root_closes_where_the_binary_search_closes_in_fewer_rounds(
    shape: Callable[[float], Residual], width: int
) -> None:
    evaluate = _one(shape(ROOT))
    binary = BisectionAdapter(_space(), rel_tol=REL_TOL)
    binary_rounds = _close(binary, evaluate, 1)
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL)

    rounds = _close(adapter, evaluate, width)

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
    binary = BisectionAdapter(_space(), rel_tol=REL_TOL, roots=2)
    binary_rounds = _close(binary, evaluate, 1)
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, roots=2)

    rounds = _close(adapter, evaluate, width)

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
    binary = BisectionAdapter(_space(), rel_tol=REL_TOL, **options)
    binary_rounds = _close(binary, evaluate, 1)
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, **options)

    rounds = _close(adapter, evaluate, width)

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
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, **options)

    _close(adapter, evaluate, width)

    assert adapter.converged()
    assert _contains(adapter.bracket, WIGGLE[2])


def test_the_first_round_in_four_parts_keeps_the_upper_quarter() -> None:
    options, evaluate = SCENARIOS["one_wiggle"]
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, **options)
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
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, **options)

    with caplog.at_level(logging.WARNING):
        _close(adapter, evaluate, 4)

    assert adapter.converged()
    assert _contains(adapter.bracket, WIGGLE[0])
    assert "changes sign 3 times" in caplog.text


# --------------------------------------------------------------------------- #
# Two brackets share each round
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("width", [2, 3, 4, 7])
def test_two_brackets_share_each_round_and_no_point_is_asked_twice(width: int) -> None:
    options, evaluate = SCENARIOS["two_step"]
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, **options)

    rounds = _close(adapter, evaluate, width)

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
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, roots=2)

    rounds = _close(adapter, evaluate, 4)

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
    assert BisectionAdapter(_space(), rel_tol=REL_TOL, batch=batch).counted_budget.counts == one


def test_the_adapter_counts_the_widest_ask_once_it_is_asked() -> None:
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, roots=2)
    assert adapter.counted_budget == root_search_budget(*BOUNDS, roots=2)

    adapter.ask(4)

    assert adapter.counted_budget == root_search_budget(*BOUNDS, roots=2, batch=4)


def test_a_batch_below_one_point_is_refused() -> None:
    with pytest.raises(OptimizerError, match="at least one point"):
        root_search_budget(*BOUNDS, batch=0)
    with pytest.raises(OptimizerError, match="at least one point"):
        BisectionAdapter(_space(), batch=0)


@pytest.mark.parametrize(("name", "width"), [("one_step", 4), ("two_step", 4), ("two_step", 7)])
def test_the_evaluations_left_are_the_evaluations_spent(name: str, width: int) -> None:
    options, evaluate = SCENARIOS[name]
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, **options)
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
    adapter = BisectionAdapter(_space(), rel_tol=REL_TOL, roots=2, **options)
    rounds: list[int] = []
    ask = adapter.ask

    def counted_ask(n: int = 1) -> list[ParamSuggestion]:
        suggestions = ask(n)
        if suggestions:
            rounds.append(len(suggestions))
        return suggestions

    adapter.ask = counted_ask  # type: ignore[method-assign]
    session = CalibrationEngine(
        space=adapter.space,
        optimizer=adapter,
        evaluator=_two(_step(ROOT_MIN), _step(ROOT_MAX)),
        max_iter=AUTO_BUDGET,
        parallel=parallel,
    ).run()
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

_TOML = """
[calibration]
method = "bisection"
max_iter = {max_iter}
{workers}

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
transform = "log"
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
max_iter = {max_iter}
{workers}
"""


def _load(tmp_path: Path, *, workers: str = "", phase: str | None = None, max_iter: int = 24):
    text = _TOML.format(
        max_iter=max_iter,
        workers=workers,
        phase="" if phase is None else _PHASE.format(max_iter=max_iter, workers=phase),
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
    findings = _check_the_budgets(_load(tmp_path, workers=workers, phase=phase))

    assert [finding.severity for finding in findings] == [severity]
    if severity == "error":
        assert "below the 26 evaluations" in findings[0].detail
