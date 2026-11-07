"""The simulation window and its stress periods, resolved from ``[simulation.time]``."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest
from pydantic import ValidationError

from hydromodpy.core.time.window import (
    ResolvedSimulationTimeWindow,
    ResolvedSteadySimulationTimeGrid,
    build_simulation_time_boundaries,
    has_flow_simulation_process,
    nominal_step_days,
    parse_step_spec,
    reject_invalid_step_value_spec,
    require_flow_simulation_time_grid,
    resolve_simulation_time_grid,
    resolve_simulation_time_window,
    resolve_simulation_time_window_dates,
    simulation_time_pandas_frequency,
    validate_recharge_coverage,
)
from hydromodpy.solver.base.simulation_config import SimulationTimeConfig


def _cfg(
    start="2020-01-01",
    end="2020-01-10",
    step_value=1,
    step_unit="day",
    *,
    policy="error",
    mode="explicit",
    regime=None,
    processes=None,
    substeps=None,
):
    time = SimpleNamespace(
        mode=mode,
        start_datetime=start,
        end_datetime=end,
        step_value=step_value,
        step_unit=step_unit,
        coverage_policy=policy,
    )
    if substeps is not None:
        time.substeps_per_period = substeps
    kwargs = {"simulation": SimpleNamespace(time=time, process=processes)}
    if regime is not None:
        kwargs["flow"] = SimpleNamespace(flow_regime=regime)
    return SimpleNamespace(**kwargs)


def _window(start, end, step_value, step_unit, policy="error"):
    return ResolvedSimulationTimeWindow(
        start=pd.Timestamp(start),
        end=pd.Timestamp(end),
        step_value=step_value,
        step_unit=step_unit,
        coverage_policy=policy,
    )


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        ("7 days", None, (7, "day")),
        (7, "day", (7, "day")),
        (2, "hours", (2, "hour")),
        (3, "mo", (3, "month")),
        (1, "months", (1, "month")),
        ("1 year", None, (1, "year")),
        ("5", "years", (5, "year")),
        (7, " day ", (7, "day")),
    ],
)
def test_a_step_is_read_as_a_count_and_a_canonical_unit(value, unit, expected):
    assert parse_step_spec(value, unit) == expected


@pytest.mark.parametrize(
    ("value", "unit", "match"),
    [
        (True, "day", "positive integer"),
        (-2, "day", "positive integer"),
        ("-2", "day", "positive integer"),
        (1.5, "day", "positive integer"),
        (1, None, "has no unit"),
        (1, "  ", "has no unit"),
        (1, "fortnight", "step_unit must be one of"),
        (1, "minute", "step_unit must be one of"),
        ("2 days", "month", "conflicts with simulation.time.step_unit"),
    ],
)
def test_a_bad_step_is_refused_with_the_reason(value, unit, match):
    with pytest.raises(ValueError, match=match):
        parse_step_spec(value, unit)


@pytest.mark.parametrize(
    ("value", "unit", "days"),
    [(1, "day", 1.0), (6, "hour", 0.25), (1, "month", 30.4375), (1, "year", 365.25)],
)
def test_the_nominal_step_length_is_in_days(value, unit, days):
    assert nominal_step_days(value, unit) == pytest.approx(days)


def test_a_window_is_resolved_to_timestamps_and_date_bounds():
    window = resolve_simulation_time_window(_cfg(start="2020-01-01 06:00", end="2020-03-31"))
    assert window.start == pd.Timestamp("2020-01-01 06:00")
    assert window.to_date_bounds() == ("2020-01-01", "2020-03-31")


def test_no_time_section_means_no_window_no_grid_no_dates():
    cfg = SimpleNamespace(simulation=SimpleNamespace())
    assert resolve_simulation_time_window(cfg) is None
    assert resolve_simulation_time_grid(cfg) is None
    assert resolve_simulation_time_window_dates(cfg) is None
    assert resolve_simulation_time_window(SimpleNamespace()) is None


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"mode": "rolling"}, "mode must be 'explicit'"),
        ({"start": None}, "start_datetime must be a valid datetime"),
        ({"end": "not a date"}, "end_datetime"),
        ({"start": "2020-02-01", "end": "2020-01-01"}, "greater than or equal"),
        ({"policy": "sometimes"}, "coverage_policy must be one of"),
    ],
)
def test_a_bad_window_is_refused_with_the_reason(kwargs, match):
    with pytest.raises(ValueError, match=match):
        resolve_simulation_time_window(_cfg(**kwargs))


def test_a_coverage_policy_is_read_whatever_its_case_and_spaces():
    assert resolve_simulation_time_window(_cfg(policy=" WARN ")).coverage_policy == "warn"


def test_the_dates_of_a_bad_window_are_none_unless_strict():
    cfg = _cfg(start="2020-02-01", end="2020-01-01")
    assert resolve_simulation_time_window_dates(cfg, strict=False) is None
    with pytest.raises(ValueError):
        resolve_simulation_time_window_dates(cfg)


def test_the_dates_of_a_good_window_are_iso_strings():
    assert resolve_simulation_time_window_dates(_cfg()) == ("2020-01-01", "2020-01-10")


@pytest.mark.parametrize(
    ("start", "end", "value", "unit", "n_periods"),
    [
        ("2020-01-01", "2020-01-10", 1, "day", 10),
        ("2020-01-01", "2020-01-10", 5, "day", 2),
        ("2020-01-01 00:00", "2020-01-01 23:00", 1, "hour", 24),
        ("2020-01-01", "2020-12-31", 1, "month", 12),
        ("2020-01-01", "2021-12-31", 1, "year", 2),
        ("2020-01-01", "2020-12-31", 3, "month", 4),
    ],
)
def test_the_boundaries_cut_the_window_into_whole_steps(start, end, value, unit, n_periods):
    bounds = build_simulation_time_boundaries(_window(start, end, value, unit))
    assert len(bounds) == n_periods + 1
    assert bounds[0] == pd.Timestamp(start)
    assert all(b > a for a, b in zip(bounds[:-1], bounds[1:], strict=True))


def test_the_period_lengths_sum_to_the_window_and_follow_the_calendar():
    grid = resolve_simulation_time_grid(_cfg("2020-01-01", "2020-12-31", 1, "month", substeps=3))
    assert grid.nper == 12
    assert grid.nstp_per_period == 3
    assert grid.period_lengths_seconds[1] == 29 * 86400  # Feb 2020
    assert sum(grid.period_lengths_seconds) == 366 * 86400
    assert grid.period_starts[0] == pd.Timestamp("2020-01-01")
    assert grid.period_ends_exclusive[-1] == pd.Timestamp("2021-01-01")


def test_an_end_that_cuts_a_step_is_refused():
    with pytest.raises(ValueError, match="not aligned"):
        build_simulation_time_boundaries(_window("2020-01-01", "2020-01-10", 3, "day"))


def test_a_window_that_ends_before_it_starts_has_no_boundaries():
    with pytest.raises(ValueError, match="greater than or equal"):
        build_simulation_time_boundaries(_window("2020-02-01", "2020-01-01", 1, "day"))


def test_explicit_period_bounds_replace_the_cut_and_joined_gaps_are_kept():
    window = ResolvedSimulationTimeWindow(
        start=pd.Timestamp("2020-01-01"),
        end=pd.Timestamp("2020-01-10"),
        step_value=1,
        step_unit="day",
        coverage_policy="error",
        period_bounds=(
            (pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-03")),
            (pd.Timestamp("2020-01-03"), pd.Timestamp("2020-01-06")),
            (pd.Timestamp("2020-01-07"), pd.Timestamp("2020-01-08")),
        ),
    )
    assert [str(b.date()) for b in build_simulation_time_boundaries(window)] == [
        "2020-01-01",
        "2020-01-03",
        "2020-01-06",
        "2020-01-07",
        "2020-01-08",
    ]


@pytest.mark.parametrize(
    ("unit", "anchor", "alias"),
    [
        ("hour", "start", "2h"),
        ("day", "start", "2D"),
        ("month", "start", "2MS"),
        ("month", "end", "2ME"),
        ("year", "start", "2YS"),
        ("year", "end", "2YE"),
    ],
)
def test_the_pandas_alias_follows_unit_and_anchor(unit, anchor, alias):
    window = _window("2020-01-01", "2020-12-31", 2, unit)
    assert simulation_time_pandas_frequency(window, anchor=anchor) == alias


def test_a_frequency_anchor_must_be_start_or_end():
    with pytest.raises(ValueError, match="anchor must be"):
        simulation_time_pandas_frequency(
            _window("2020-01-01", "2020-01-02", 1, "day"), anchor="mid"
        )


def test_an_unknown_unit_has_no_frequency_and_no_boundaries():
    window = _window("2020-01-01", "2020-01-02", 1, "week")
    with pytest.raises(ValueError, match="Unsupported"):
        simulation_time_pandas_frequency(window)
    with pytest.raises(ValueError, match="Unsupported"):
        build_simulation_time_boundaries(window)


@pytest.mark.parametrize("step_value", [1, 3, 10], ids=["short", "not-fitting", "whole-window"])
def test_a_steady_run_has_one_period_over_the_whole_window(step_value):
    grid = resolve_simulation_time_grid(
        _cfg("2020-01-01", "2020-01-10", step_value, "day", regime="steady")
    )
    assert grid.nper == 1
    assert grid.period_lengths_seconds == (10 * 86400.0,)


def test_a_transient_regime_keeps_the_step():
    assert resolve_simulation_time_grid(_cfg(regime="transient")).nper == 10


@pytest.mark.parametrize(
    ("processes", "expected"),
    [
        (None, False),
        ([], False),
        ({"kind": "flow"}, True),
        (SimpleNamespace(kind=" Flow "), True),
        ([{"kind": "transport"}, SimpleNamespace(kind="flow")], True),
        (({"kind": "transport"},), False),
    ],
)
def test_a_flow_process_is_found_in_any_container_and_spelling(processes, expected):
    assert has_flow_simulation_process(_cfg(processes=processes)) is expected


def test_without_a_flow_process_the_grid_is_returned_as_is():
    assert require_flow_simulation_time_grid(_cfg(processes=None)).nper == 10


def test_a_flow_run_gets_the_grid_of_its_time_section():
    grid = require_flow_simulation_time_grid(_cfg(processes=[{"kind": "flow"}]))
    assert grid.nper == 10


def test_a_steady_flow_run_may_omit_the_time_section():
    cfg = SimpleNamespace(
        simulation=SimpleNamespace(process=[{"kind": "flow"}]),
        flow=SimpleNamespace(flow_regime="steady"),
    )
    grid = require_flow_simulation_time_grid(cfg)
    assert isinstance(grid, ResolvedSteadySimulationTimeGrid)
    assert grid.nper == 1
    assert grid.period_starts == ()
    assert grid.period_ends_exclusive == ()


@pytest.mark.parametrize(
    "flow",
    [
        None,
        SimpleNamespace(flow_regime=None),
        SimpleNamespace(flow_regime="weird"),
        SimpleNamespace(flow_regime="transient"),
    ],
)
def test_a_transient_flow_run_without_time_section_is_refused(flow):
    cfg = SimpleNamespace(simulation=SimpleNamespace(process=[{"kind": "flow"}]))
    if flow is not None:
        cfg.flow = flow
    with pytest.raises(ValueError, match="require a valid \\[simulation.time\\]"):
        require_flow_simulation_time_grid(cfg)


_WIN = _window("2020-01-01", "2020-01-04", 1, "day")


def _series(index, values=None):
    index = pd.to_datetime(index)
    return pd.Series(values if values is not None else [1.0] * len(index), index=index)


def test_a_window_that_is_absent_or_ignored_checks_nothing():
    validate_recharge_coverage(None, None)
    validate_recharge_coverage(None, _window("2020-01-01", "2020-01-04", 1, "day", "ignore"))


@pytest.mark.parametrize(
    "recharge",
    [
        None,
        pd.DataFrame(),
        [1, 2, 3],
        pd.Series([1.0], index=["a"]),
        pd.Series([], dtype=float, index=pd.DatetimeIndex([])),
    ],
    ids=["missing", "empty-frame", "not-a-series", "index-not-datetime", "empty-series"],
)
def test_an_unusable_recharge_is_refused_under_error_and_warned_under_warn(recharge):
    with pytest.raises(ValueError, match="Recharge coverage check"):
        validate_recharge_coverage(recharge, _WIN)
    with pytest.warns(UserWarning, match="Recharge coverage check"):
        validate_recharge_coverage(recharge, _window("2020-01-01", "2020-01-04", 1, "day", "warn"))


def test_a_series_on_the_period_starts_is_accepted():
    validate_recharge_coverage(_series(pd.date_range("2020-01-01", periods=4)), _WIN)


def test_a_dataframe_uses_its_first_column_and_unsorted_input_is_sorted():
    frame = _series(["2020-01-03", "2020-01-01", "2020-01-02", "2020-01-04"]).to_frame()
    validate_recharge_coverage(frame, _WIN)


def test_a_string_index_that_reads_as_dates_is_accepted():
    s = pd.Series([1.0] * 4, index=["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"])
    validate_recharge_coverage(s, _WIN)


def test_a_record_that_stops_before_the_window_is_refused_and_a_longer_one_accepted():
    with pytest.raises(ValueError, match="does not cover"):
        validate_recharge_coverage(_series(["2019-12-01", "2019-12-02"]), _WIN)
    validate_recharge_coverage(_series(pd.date_range("2019-12-01", "2020-02-01")), _WIN)


def test_a_nan_inside_the_window_is_refused_but_one_outside_is_not():
    days = pd.date_range("2019-12-30", "2020-01-06")
    inside = _series(days, [1.0] * len(days))
    inside.loc["2020-01-02"] = float("nan")
    with pytest.raises(ValueError, match="NaN values"):
        validate_recharge_coverage(inside, _WIN)
    outside = _series(days, [1.0] * len(days))
    outside.loc["2019-12-30"] = float("nan")
    validate_recharge_coverage(outside, _WIN)


# Both step_value callers share one refusal rule.
#
# ``SimulationTimeConfig`` (Pydantic validation at config load) and
# ``resolve_simulation_time_window`` (the launcher window helper) must reject
# the same bad ``step_value``/``step_unit`` inputs with the same message, since
# both delegate to ``reject_invalid_step_value_spec``.


_SHARED_REFUSALS = [
    (-5, None, "must be a positive integer"),
    (0, "day", "must be a positive integer"),
    (1, None, "has no unit"),
]


@pytest.mark.parametrize(("step_value", "step_unit", "match"), _SHARED_REFUSALS)
def test_planning_config_and_window_helper_refuse_the_same_inputs(
    step_value: object, step_unit: object, match: str
) -> None:
    with pytest.raises(ValidationError, match=match):
        SimulationTimeConfig(
            start_datetime="2020-01-01 00:00:00",
            end_datetime="2020-01-02 00:00:00",
            step_value=step_value,
            step_unit=step_unit,
        )

    with pytest.raises(ValueError, match=match):
        resolve_simulation_time_window(
            _cfg("2020-01-01 00:00:00", "2020-01-02 00:00:00", step_value, step_unit)
        )


def test_shared_rule_rejects_a_boolean_step_value_before_the_missing_unit_check() -> None:
    """Pydantic coerces a bare bool to int before validation, so this edge only
    reaches ``reject_invalid_step_value_spec`` untouched through the window
    helper's plain-object callers; exercise the shared function directly.
    """
    with pytest.raises(ValueError, match="must be a positive integer"):
        reject_invalid_step_value_spec(True, None)
