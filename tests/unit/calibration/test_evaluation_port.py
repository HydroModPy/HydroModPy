"""Tests of `evaluation.port`."""

from __future__ import annotations

import math
from datetime import date
from pathlib import Path

import pytest

from hydromodpy.calibration.evaluation import registry
from hydromodpy.calibration.evaluation import registry as evaluation_registry
from hydromodpy.calibration.evaluation.analytic_bowl import BOWL_OPTIMUM, AnalyticBowlEvaluator
from hydromodpy.calibration.evaluation.port import TrialOutcome, TrialRequest
from hydromodpy.calibration.optim.parameters import CalibParameter, ParameterSpace
from hydromodpy.calibration.report import CalibrationReport
from hydromodpy.calibration.runners.cli_runner import run_calibration_cli
from hydromodpy.calibration.runners.recap import result_lines
from hydromodpy.results.session.descriptor import ScoredSamples, read_session
from hydromodpy.results.session.summary import session_summary, summary_rows
from hydromodpy.results.session.view import Session
from tests._helpers.session_documents import calibration_window

# From test_a_session_partial_for_a_failed_trial_names_it.py
# A session left ``partial`` by a failed trial names that trial.
#
# A search can meet its stopping rule and still close ``partial`` because one
# trial failed. The message written to ``session.json`` then read the name of
# the stopping rule, as if the budget had run out. It now names the failed
# trials, and the stopping rule only when the rule was not met.


class _OneFailureProbe:
    """The second trial fails, the others complete."""

    evaluator_id = "test_one_failure_probe"
    needs_prepared_model = False
    calls = 0

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        _OneFailureProbe.calls += 1
        if _OneFailureProbe.calls == 2:
            return TrialOutcome(
                cost=math.nan, status="failed", duration_s=0.0, error="solver diverged"
            )
        return TrialOutcome(cost=float(request.values["K"]), status="completed", duration_s=0.0)


@pytest.fixture
def one_failure_probe():
    _OneFailureProbe.calls = 0
    evaluation_registry.evaluators.register(_OneFailureProbe, replace=True)
    try:
        yield _OneFailureProbe
    finally:
        evaluation_registry.evaluators.unregister(_OneFailureProbe.evaluator_id)


PROBE_TOML = """
[calibration]
method = "grid"
max_trials = 3
evaluator = "test_one_failure_probe"
use_cache = false
save_runs = "none"
method_options = { points_per_dim = 3 }

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
map.complete = "streams.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


def test_the_message_names_the_failed_trial_not_the_rule(tmp_path: Path, one_failure_probe) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(PROBE_TOML, encoding="utf-8")

    report = run_calibration_cli(path, workspace=tmp_path)

    descriptor = read_session(report.session_dir)
    assert report.extra["search"]["converged"] is True
    assert descriptor.status == "partial"
    assert descriptor.error_message == "1 trial(s) failed: trial 2"


# From test_the_recap_says_what_the_cost_was_scored_on.py
# The console recap of a calibration says what its cost was scored on.
#
# ``hmp calibrate`` and the recap of ``hmp run`` printed the best cost and its
# metric, never the samples behind it: no window, no count. The only dated line
# read the first trial, not the trial whose cost was printed. The report now
# carries the pairs the best trial was scored on (count, first and last period
# end stamp, per output) and the window the search declares, and both recaps
# print them beside the cost.


class _ScoredSetProbe:
    """Each trial pairs a different count; the cost falls as K rises."""

    evaluator_id = "test_scored_set_probe"
    needs_prepared_model = False
    calls = 0

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        _ScoredSetProbe.calls += 1
        k = float(request.values["K"])
        n = 100 + _ScoredSetProbe.calls
        return TrialOutcome(
            cost=-k,
            status="completed",
            duration_s=0.0,
            components={
                "q.n_paired": float(n),
                "q.date_start": float(date(2016, 1, 1).toordinal()),
                "q.date_end": float(date(2021, 1, 1).toordinal()),
                "probe.k": k,
            },
        )


@pytest.fixture
def scored_set_probe():
    _ScoredSetProbe.calls = 0
    evaluation_registry.evaluators.register(_ScoredSetProbe, replace=True)
    try:
        yield _ScoredSetProbe
    finally:
        evaluation_registry.evaluators.unregister(_ScoredSetProbe.evaluator_id)


PROBE_TOML__recap_says = """
[calibration]
method = "grid"
max_trials = 3
evaluator = "test_scored_set_probe"
use_cache = false
method_options = { points_per_dim = 3 }
window = { start = "2016-01-01", end = "2020-12-31" }

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
map.complete = "streams.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


def test_the_report_carries_the_pairs_of_the_best_trial(tmp_path: Path, scored_set_probe) -> None:
    path = tmp_path / "calibration.toml"
    path.write_text(PROBE_TOML__recap_says, encoding="utf-8")

    report = run_calibration_cli(path, workspace=tmp_path)

    trials = report.trials
    best = trials.loc[trials["cost"].idxmin()]
    assert int(best["trial"]) != 1  # the best is not the first trial
    assert report.extra["cost_samples"] == {
        "q": {
            "n_paired": int(best["components"]["q.n_paired"]),
            "start": "2016-01-01",
            "end": "2021-01-01",
        }
    }
    assert report.extra["cost_window"] == "window 2016-01-01 to 2020-12-31"


def _report(extra: dict) -> CalibrationReport:
    return CalibrationReport(
        session_id="abc123",
        method="grid",
        n_trials=4,
        best_cost=0.334115,
        duration_s=1.0,
        save_runs="none",
        promoted=0,
        best_parameters={"Sy": 0.045},
        extra=extra,
    )


SCORED = {
    "cost_metric": "1 - nse_log",
    "cost_window": "window 2016-01-01 to 2020-12-31",
    "cost_samples": {"hydrograph": {"n_paired": 1828, "start": "2016-01-01", "end": "2021-01-01"}},
}


def test_hmp_calibrate_prints_the_pairs_beside_the_cost() -> None:
    lines = result_lines(_report(SCORED))

    cost = lines.index("  cost: 0.334115 (1 - nse_log)")
    assert lines[cost + 1] == (
        "  scored on: hydrograph 1828 pair(s), period ends 2016-01-01 to 2021-01-01, "
        "best trial (window 2016-01-01 to 2020-12-31)"
    )


def test_hmp_calibrate_prints_the_declared_window_when_no_pair_was_counted() -> None:
    extra = {"cost_metric": "1 - nse_log", "cost_window": "window 2016-01-01 to 2020-12-31"}

    lines = result_lines(_report(extra))

    assert "  scored on: window 2016-01-01 to 2020-12-31, pairs not counted" in lines


# From test_the_session_records_the_pairs_its_cost_was_scored_on.py
# ``session.json`` records the pairs the kept cost was scored on.
#
# ``windows`` holds the declared window completed by the dates of the
# TOML: 2016-01-01 to 2020-12-31, 1827 days. A daily cost scored on it holds
# the 1827 periods lying in it, whose end stamps run from 2016-01-02 to
# 2021-01-01 (the session read the end stamp before decision m01, and scored
# 1828 pairs from 2016-01-01). The window stays as
# it is, since ``calibrated_by.windows`` is read from it to label a run
# ``evaluated`` (decision m08). Beside it the descriptor now carries, per dated
# output, the count and the first and last stamp of the best trial, and the HTML
# report prints both.


class _DailyProbe:
    """Pairs 1827 daily stamps on the best trial, fewer on the others."""

    evaluator_id = "test_daily_scored_set_probe"
    needs_prepared_model = False

    def evaluate(self, request: TrialRequest) -> TrialOutcome:
        k = float(request.values["K"])
        best = k > 1e-4
        return TrialOutcome(
            cost=-k,
            status="completed",
            duration_s=0.0,
            components={
                "hydrograph.n_paired": 1827.0 if best else 1700.0,
                "hydrograph.date_start": float(date(2016, 1, 2).toordinal()),
                "hydrograph.date_end": float(date(2021, 1, 1).toordinal()),
            },
        )


@pytest.fixture
def daily_probe():
    evaluation_registry.evaluators.register(_DailyProbe, replace=True)
    try:
        yield _DailyProbe
    finally:
        evaluation_registry.evaluators.unregister(_DailyProbe.evaluator_id)


PROBE_TOML__session_records = """
[simulation.time]
start_datetime = 2015-01-01
end_datetime = 2020-12-31

[calibration]
method = "grid"
max_trials = 3
evaluator = "test_daily_scored_set_probe"
use_cache = false
save_runs = "none"
method_options = { points_per_dim = 3 }
window = { start = "2016-01-01" }

[calibration.parameters.K]
bounds = [1e-7, 1e-3]
search_space = "log"
path = "flow.param.K.field.value"

[calibration.outputs.net]
support = "network"
map.complete = "streams.gpkg"

[[calibration.objective_blocks]]
name = "network"
metric = "distance_gap"
uses_outputs = ["net"]
"""


@pytest.fixture
def closed_session(tmp_path: Path, daily_probe) -> Path:
    path = tmp_path / "calibration.toml"
    path.write_text(PROBE_TOML__session_records, encoding="utf-8")
    report = run_calibration_cli(path, workspace=tmp_path)
    return Path(report.session_dir)


def test_the_window_stays_the_declared_one(closed_session: Path) -> None:
    descriptor = read_session(closed_session)

    assert descriptor.windows == calibration_window(date(2016, 1, 1), date(2020, 12, 31))


def test_the_pairs_of_the_best_trial_sit_beside_it(closed_session: Path) -> None:
    descriptor = read_session(closed_session)

    assert descriptor.scored == [
        ScoredSamples(
            window="calibration",
            case_id="calibration",
            output="hydrograph",
            n=1827,
            first=date(2016, 1, 2),
            last=date(2021, 1, 1),
        )
    ]


def test_the_html_report_prints_the_window_and_the_pairs(closed_session: Path) -> None:
    summary = dict(summary_rows(session_summary(Session(closed_session))))

    assert summary["scored on"] == (
        "hydrograph 1827 pair(s), period ends 2016-01-02 to "
        "2021-01-01, best trial (window 2016-01-01 to 2020-12-31)"
    )


# ---------------------------------------------------------------------------
# evaluation_analytic_bowl
# Tests of `evaluation.analytic_bowl`.
# ---------------------------------------------------------------------------

# From test_analytic_bowl_evaluator.py
# The surface a rehearsal is scored against, and what it refuses to invent.
#
# The conformance suite holds this evaluator to the port, alongside every other
# evaluator the installation serves. What it cannot hold it to is what it
# computes, because that is this evaluator's own business: that the optimum sits
# where the docstring says it sits, that a log-scaled parameter is positioned
# geometrically, and that an unscorable sample comes back carrying ``nan``. A user
# who names ``analytic_bowl`` to rehearse a montage reads the search against a
# known answer, so the answer has to be the one that was promised.

pytestmark = pytest.mark.fast


def _space(*parameters: CalibParameter) -> ParameterSpace:
    return ParameterSpace(parameters)


LOG_K = CalibParameter(name="k", lower=1e-6, upper=1e-2, search_space="log")
POROSITY = CalibParameter(name="porosity", lower=0.1, upper=0.3)


def _bowl(*parameters: CalibParameter) -> AnalyticBowlEvaluator:
    return AnalyticBowlEvaluator(space=_space(*parameters))


def _ask(bowl: AnalyticBowlEvaluator, values: dict[str, float]):
    return bowl.evaluate(TrialRequest(trial_id=1, values=values))


def _optimum(*parameters: CalibParameter) -> dict[str, float]:
    """The sample the bowl calls its minimum, read off the bounds.

    Read rather than written as a literal: ``0.2`` and the midpoint of
    ``[0.1, 0.3]`` are two different binary numbers, and a user rehearsing a
    montage gets the optimum from the interval the same way.
    """
    return {
        parameter.name: parameter.to_physical(
            BOWL_OPTIMUM * (parameter.lower_transformed + parameter.upper_transformed)
        )
        for parameter in parameters
    }


class TestWhereTheOptimumIs:
    def test_the_middle_of_every_interval_costs_nothing(self) -> None:
        outcome = _ask(_bowl(LOG_K, POROSITY), _optimum(LOG_K, POROSITY))

        assert outcome.status == "completed"
        assert outcome.cost == pytest.approx(0.0, abs=1e-24)

    def test_a_log_parameter_is_positioned_geometrically_and_not_arithmetically(self) -> None:
        """``5e-3`` is the middle of ``[1e-6, 1e-2]`` on a ruler and nowhere near it on a log.

        This is the difference between a conductivity read the way it is known
        and one read the way it is written, and it is the reason the bowl asks
        the parameter for its own transform instead of subtracting bounds.
        """
        bowl = _bowl(LOG_K)

        geometric = _ask(bowl, {"k": 1e-4})
        arithmetic = _ask(bowl, {"k": 5e-3})

        assert geometric.cost == pytest.approx(0.0, abs=1e-24)
        assert arithmetic.cost > 0.15

    def test_both_bounds_are_equally_far_from_it(self) -> None:
        bowl = _bowl(LOG_K)

        assert _ask(bowl, {"k": 1e-6}).cost == pytest.approx(BOWL_OPTIMUM**2)
        assert _ask(bowl, {"k": 1e-2}).cost == pytest.approx(BOWL_OPTIMUM**2)

    def test_the_cost_is_the_mean_of_its_components_so_a_dimension_does_not_dilute_it(self) -> None:
        """A sum would make a two-parameter document score twice a one-parameter one."""
        one = _ask(_bowl(LOG_K), {"k": 1e-6})
        two = _ask(_bowl(LOG_K, POROSITY), {"k": 1e-6, "porosity": 0.1})

        assert one.cost == pytest.approx(two.cost)
        assert set(two.components) == {"k", "porosity"}
        assert two.cost == pytest.approx(sum(two.components.values()) / 2)

    def test_a_value_outside_its_bounds_is_scored_and_not_clipped(self) -> None:
        """An optimizer that leaves the box has to be told it is getting worse."""
        bowl = _bowl(POROSITY)

        assert _ask(bowl, {"porosity": 0.4}).cost > _ask(bowl, {"porosity": 0.3}).cost


class TestWhatItRefusesToInvent:
    def test_a_name_the_space_never_declared_fails_and_says_which(self) -> None:
        outcome = _ask(_bowl(LOG_K), {"k": 1e-4, "storage": 1e-3})

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)
        assert "storage" in str(outcome.error)

    def test_a_value_its_own_transform_cannot_take_fails_rather_than_raising(self) -> None:
        """A negative conductivity has no logarithm, and a search must not stop on one."""
        outcome = _ask(_bowl(LOG_K), {"k": -1.0})

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)
        assert "log" in str(outcome.error)

    def test_a_sample_that_is_not_a_number_fails_rather_than_costing_nothing(self) -> None:
        outcome = _ask(_bowl(POROSITY), {"porosity": math.nan})

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)

    def test_a_parameter_the_sample_omits_is_not_scored_against_a_made_up_value(self) -> None:
        """There is nothing to fabricate one from, and fabricating one would move the optimum."""
        outcome = _ask(_bowl(LOG_K, POROSITY), {"k": 1e-4})

        assert outcome.status == "completed"
        assert set(outcome.components) == {"k"}

    def test_an_empty_sample_costs_nothing_and_completes(self) -> None:
        """A document declaring no parameter makes every optimizer ask with ``{}``."""
        outcome = _ask(_bowl(LOG_K), {})

        assert outcome.status == "completed"
        assert outcome.cost == 0.0
        assert outcome.components == {}

    def test_a_pinned_parameter_sits_at_the_optimum_instead_of_dividing_by_zero(self) -> None:
        """Pinning a value is how a document takes a dimension out of a search."""
        pinned = CalibParameter(name="pinned", lower=2.0, upper=2.0)

        outcome = _ask(_bowl(pinned), {"pinned": 2.0})

        assert outcome.status == "completed"
        assert outcome.cost == 0.0

    def test_a_pinned_parameter_takes_a_sample_out_of_the_cost_not_out_of_the_checks(self) -> None:
        """The order the adversarial gate of F9b forced, and the reason it matters.

        A pinned dimension has no interval, so a position read before the value
        was faced returned the optimum for a value nothing can read: ``-5.0``
        under a log transform came back ``completed`` at cost ``0.0`` -- the best
        score the surface has, handed to the sample that deserves it least. Worse
        than the failure mode this port forbids, which is a failed trial carrying
        a large finite number.

        One value and not three on purpose: only a value the *transform* refuses
        goes through the reordered call. ``nan`` and ``inf`` are refused one step
        earlier, and they are asserted in their own test rather than folded in
        here, where they would look like coverage of an order they never reach.
        """
        pinned_log = CalibParameter(name="k", lower=1e-4, upper=1e-4, search_space="log")

        outcome = _ask(_bowl(pinned_log), {"k": -5.0})

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)
        assert "log" in str(outcome.error)

    def test_a_pinned_parameter_refuses_an_infinite_sample_like_any_other(self) -> None:
        """Faced on the value, so having no interval does not exempt it."""
        pinned = CalibParameter(name="pinned", lower=2.0, upper=2.0)
        bowl = _bowl(pinned)

        for unscorable in (math.nan, math.inf, -math.inf):
            outcome = _ask(bowl, {"pinned": unscorable})

            assert outcome.status == "failed", f"{unscorable!r} was scored"
            assert math.isnan(outcome.cost)
            assert outcome.error

    def test_a_value_that_is_not_a_number_at_all_fails_rather_than_raising(self) -> None:
        """``values`` is typed as floats, and a search must not stop on a caller's slip."""
        for unreadable in ("wet", None, [0.2], 10**400):
            outcome = _ask(_bowl(POROSITY), {"porosity": unreadable})

            assert outcome.status == "failed", f"{unreadable!r} did not come back"
            assert math.isnan(outcome.cost)
            assert "not a number this can read" in str(outcome.error)

    def test_a_finite_sample_whose_squared_distance_overflows_fails(self) -> None:
        narrow = CalibParameter(name="narrow", lower=0.0, upper=1e-200)

        outcome = _ask(_bowl(narrow), {"narrow": 1.0})

        assert outcome.status == "failed"
        assert math.isnan(outcome.cost)

    def test_a_position_beyond_the_float_range_fails(self) -> None:
        sliver = CalibParameter(name="sliver", lower=0.0, upper=1e-320)

        outcome = _ask(_bowl(sliver), {"sliver": 1.0})

        assert outcome.status == "failed"
        assert "does not land anywhere" in str(outcome.error)

    def test_a_mean_uses_finite_terms_without_overflowing_the_sum(self) -> None:
        first = CalibParameter(name="first", lower=0.0, upper=1e-154)
        second = CalibParameter(name="second", lower=0.0, upper=1e-154)

        outcome = _ask(_bowl(first, second), {"first": 1.0, "second": 1.0})

        assert outcome.status == "completed"
        assert outcome.cost == pytest.approx(1e308)


class TestWhatItIsBuiltWith:
    def test_without_a_space_it_says_what_a_space_is_for(self) -> None:
        with pytest.raises(ValueError, match="space"):
            AnalyticBowlEvaluator(space=None)

    def test_the_registry_resolves_it_without_the_workflow_stack_behind_it(self) -> None:
        """The reason it is a built-in and not a test double: a rehearsal has to be cheap."""

        assert registry.evaluators.get("analytic_bowl") is AnalyticBowlEvaluator
        assert registry.needs_prepared_model("analytic_bowl") is False
        assert "analytic_bowl" in registry.evaluators.names(shipped_only=True)


def test_an_outcome_without_a_profile_stays_valid_and_a_surrogate_returns_none() -> None:
    from datetime import UTC, datetime

    from hydromodpy.results.storage.run_profile import ProfileLine

    plain = TrialOutcome(cost=1.0, status="completed", duration_s=0.1)
    assert plain.profile == ()

    outcome = _bowl(POROSITY).evaluate(TrialRequest(trial_id=1, values={"porosity": 0.2}))
    assert outcome.status == "completed"
    assert outcome.profile == ()

    line = ProfileLine(
        kind="solve",
        name="flow",
        attempt=1,
        started_at=datetime(2026, 11, 11, tzinfo=UTC),
        duration_s=0.2,
        reused="rerun",
    )
    timed = TrialOutcome(cost=1.0, status="completed", duration_s=0.1, profile=(line,))
    assert timed.profile == (line,)
