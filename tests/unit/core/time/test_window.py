"""The simulation window and its stress periods, resolved from ``[simulation.time]``."""

from __future__ import annotations

import dataclasses
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.exceptions import ConfigError
from hydromodpy.core.time.window import (
    ChainWindow,
    ResolvedSimulationTimeWindow,
    ResolvedSteadySimulationTimeGrid,
    build_simulation_time_boundaries,
    chain_windows,
    has_flow_simulation_process,
    nominal_step_days,
    parse_step_spec,
    parse_window_length,
    reject_invalid_step_value_spec,
    require_flow_simulation_time_grid,
    resolve_simulation_time_grid,
    resolve_simulation_time_window,
    resolve_simulation_time_window_dates,
    simulation_time_pandas_frequency,
    time_grid_start,
    validate_recharge_coverage,
    window_grid,
)
from tests._helpers.model_factory import make_model


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
def test_step_spec(value, unit, expected):
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
def test_bad_step_refusals(value, unit, match):
    with pytest.raises(ValueError, match=match):
        parse_step_spec(value, unit)


@pytest.mark.parametrize(
    ("value", "unit", "days"),
    [(1, "day", 1.0), (6, "hour", 0.25), (1, "month", 30.4375), (1, "year", 365.25)],
)
def test_nominal_step_days(value, unit, days):
    assert nominal_step_days(value, unit) == pytest.approx(days)


def test_no_time_section():
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
def test_bad_window_refusals(kwargs, match):
    with pytest.raises(ValueError, match=match):
        resolve_simulation_time_window(_cfg(**kwargs))


def test_dates_of_a_bad_window():
    cfg = _cfg(start="2020-02-01", end="2020-01-01")
    assert resolve_simulation_time_window_dates(cfg, strict=False) is None
    with pytest.raises(ValueError):
        resolve_simulation_time_window_dates(cfg)


def test_dates_are_iso_strings():
    assert resolve_simulation_time_window_dates(_cfg()) == ("2020-01-01", "2020-01-10")


def test_monthly_period_lengths():
    grid = resolve_simulation_time_grid(_cfg("2020-01-01", "2020-12-31", 1, "month", substeps=3))
    assert grid.nper == 12
    assert grid.nstp_per_period == 3
    assert grid.period_lengths_seconds[1] == 29 * 86400  # Feb 2020
    assert sum(grid.period_lengths_seconds) == 366 * 86400
    assert grid.period_starts[0] == pd.Timestamp("2020-01-01")
    assert grid.period_ends_exclusive[-1] == pd.Timestamp("2021-01-01")


def test_reversed_window_refused():
    with pytest.raises(ValueError, match="greater than or equal"):
        build_simulation_time_boundaries(_window("2020-02-01", "2020-01-01", 1, "day"))


def test_explicit_period_bounds():
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
def test_pandas_frequency_alias(unit, anchor, alias):
    window = _window("2020-01-01", "2020-12-31", 2, unit)
    assert simulation_time_pandas_frequency(window, anchor=anchor) == alias


def test_bad_anchor_refused():
    with pytest.raises(ValueError, match="anchor must be"):
        simulation_time_pandas_frequency(
            _window("2020-01-01", "2020-01-02", 1, "day"), anchor="mid"
        )


def test_unknown_unit_refused():
    window = _window("2020-01-01", "2020-01-02", 1, "week")
    with pytest.raises(ValueError, match="Unsupported"):
        simulation_time_pandas_frequency(window)
    with pytest.raises(ValueError, match="Unsupported"):
        build_simulation_time_boundaries(window)


@pytest.mark.parametrize("step_value", [1, 3, 10], ids=["short", "not-fitting", "whole-window"])
def test_steady_single_period(step_value):
    grid = resolve_simulation_time_grid(
        _cfg("2020-01-01", "2020-01-10", step_value, "day", regime="steady")
    )
    assert grid.nper == 1
    assert grid.period_lengths_seconds == (10 * 86400.0,)


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
def test_flow_process_found(processes, expected):
    assert has_flow_simulation_process(_cfg(processes=processes)) is expected


def test_steady_without_time_section():
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
def test_transient_needs_time_section(flow):
    cfg = SimpleNamespace(simulation=SimpleNamespace(process=[{"kind": "flow"}]))
    if flow is not None:
        cfg.flow = flow
    with pytest.raises(ValueError, match="require a valid \\[simulation.time\\]"):
        require_flow_simulation_time_grid(cfg)


_WIN = _window("2020-01-01", "2020-01-04", 1, "day")


def _series(index, values=None):
    index = pd.to_datetime(index)
    return pd.Series(values if values is not None else [1.0] * len(index), index=index)


def test_coverage_check_skipped():
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
def test_unusable_recharge_policy(recharge):
    with pytest.raises(ValueError, match="Recharge coverage check"):
        validate_recharge_coverage(recharge, _WIN)
    with pytest.warns(UserWarning, match="Recharge coverage check"):
        validate_recharge_coverage(recharge, _window("2020-01-01", "2020-01-04", 1, "day", "warn"))


def test_recharge_frame_accepted():
    frame = _series(["2020-01-03", "2020-01-01", "2020-01-02", "2020-01-04"]).to_frame()
    validate_recharge_coverage(frame, _WIN)


def test_recharge_string_index():
    s = pd.Series([1.0] * 4, index=["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"])
    validate_recharge_coverage(s, _WIN)


def test_recharge_record_length():
    with pytest.raises(ValueError, match="does not cover"):
        validate_recharge_coverage(_series(["2019-12-01", "2019-12-02"]), _WIN)
    validate_recharge_coverage(_series(pd.date_range("2019-12-01", "2020-02-01")), _WIN)


def test_recharge_nan_in_window():
    days = pd.date_range("2019-12-30", "2020-01-06")
    inside = _series(days, [1.0] * len(days))
    inside.loc["2020-01-02"] = float("nan")
    with pytest.raises(ValueError, match="NaN values"):
        validate_recharge_coverage(inside, _WIN)
    outside = _series(days, [1.0] * len(days))
    outside.loc["2019-12-30"] = float("nan")
    validate_recharge_coverage(outside, _WIN)


def test_boolean_step_refused() -> None:
    """Pydantic coerces a bare bool to int before validation, so this edge only
    reaches ``reject_invalid_step_value_spec`` untouched through the window
    helper's plain-object callers; exercise the shared function directly.
    """
    with pytest.raises(ValueError, match="must be a positive integer"):
        reject_invalid_step_value_spec(True, None)


STARTS = (
    ("no grid", None, None),
    ("a steady run without a grid", make_model().time.grid, None),
    (
        "the first boundary",
        SimpleNamespace(boundaries=("2020-01-01", "2020-02-01")),
        "2020-01-01",
    ),
    (
        "the start of the window",
        SimpleNamespace(boundaries=(), window=SimpleNamespace(start="2019-06-01")),
        "2019-06-01",
    ),
    (
        "the first date",
        SimpleNamespace(boundaries=(), window=None, datetimes=("2018-03-03",)),
        "2018-03-03",
    ),
    ("a grid that dates nothing", SimpleNamespace(boundaries=(), window=None), None),
)


@pytest.mark.parametrize(("case", "grid", "expected"), STARTS, ids=[c[0] for c in STARTS])
def test_start_of_a_grid(case: str, grid: object, expected: str | None) -> None:
    del case

    assert time_grid_start(grid) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("6 months", (6, "month")), ("1 year", (1, "year")), ("30 days", (30, "day"))],
)
def test_window_length_spec(raw, expected):
    assert parse_window_length(raw) == expected


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("6", 'written "<n> <unit>"'),
        (6, 'written "<n> <unit>"'),
        ("1.5 months", "positive whole number"),
        ("0 days", "positive whole number"),
        ("3 weeks", "positive whole number"),
    ],
    ids=["bare text", "bare number", "fraction", "zero", "weeks"],
)
def test_bad_window_length_refusals(raw, match):
    with pytest.raises(ValueError, match=match) as raised:
        parse_window_length(raw)
    assert "simulation.time.window_length" in str(raised.value)


def _monthly(start="2020-01-01", end="2020-12-31"):
    return resolve_simulation_time_grid(_cfg(start, end, 1, "month", substeps=5))


@pytest.mark.parametrize(
    ("grid", "length", "periods"),
    [
        ("monthly", "6 months", [(0, 6), (6, 12)]),
        ("monthly", "5 months", [(0, 5), (5, 10), (10, 12)]),
        ("monthly", "1 year", [(0, 12)]),
        ("monthly", "3 years", [(0, 12)]),
        ("daily", "7 days", [(0, 7), (7, 10)]),
        ("daily", "10 days", [(0, 10)]),
    ],
    ids=["two halves", "short last", "exact year", "longer than the run", "daily", "daily one"],
)
def test_chain_windows(grid, length, periods):
    resolved = _monthly() if grid == "monthly" else resolve_simulation_time_grid(_cfg())
    windows = chain_windows(resolved, length)

    assert [(one.first_period, one.stop_period) for one in windows] == periods
    assert [one.index for one in windows] == list(range(1, len(periods) + 1))
    assert {one.count for one in windows} == {len(periods)}
    assert windows[0].start == resolved.boundaries[0]
    assert windows[-1].end == resolved.boundaries[-1]
    for before, after in zip(windows, windows[1:], strict=False):
        assert before.end == after.start
    assert sum(one.nper for one in windows) == resolved.nper


def test_window_edge_inside_period():
    weekly = resolve_simulation_time_grid(_cfg("2020-01-01", "2020-03-24", 7, "day"))

    with pytest.raises(ConfigError) as raised:
        chain_windows(weekly, "1 month")

    message = str(raised.value)
    assert "2020-02-01T00:00:00" in message
    assert "from 2020-01-29T00:00:00 to 2020-02-05T00:00:00" in message
    assert "simulation.time.window_length = '1 month'" in message


@pytest.mark.parametrize(
    "grid",
    [None, ResolvedSteadySimulationTimeGrid()],
    ids=["no time section", "steady"],
)
def test_no_periods_to_cut(grid):
    with pytest.raises(ConfigError, match="no \\[simulation.time\\] periods to cut"):
        chain_windows(grid, "6 months")


def test_window_dates():
    whole = _monthly()
    first, last = (window_grid(whole, one) for one in chain_windows(whole, "6 months"))

    assert first.window.to_date_bounds() == ("2020-01-01", "2020-06-30")
    assert last.window.to_date_bounds() == ("2020-07-01", "2020-12-31")
    assert first.window.period_bounds is None and last.window.period_bounds is None


def test_window_keeps_explicit_periods():
    """Periods written out in the whole grid stay written out in the window."""
    whole = _monthly()
    explicit = dataclasses.replace(
        whole.window,
        period_bounds=tuple(zip(whole.boundaries[:-1], whole.boundaries[1:], strict=True)),
    )
    whole = dataclasses.replace(whole, window=explicit)
    one = ChainWindow(
        index=2,
        count=2,
        first_period=6,
        stop_period=12,
        start=whole.boundaries[6],
        end=whole.boundaries[12],
    )

    cut = window_grid(whole, one)

    assert cut.window.period_bounds == explicit.period_bounds[6:12]
    assert tuple(build_simulation_time_boundaries(cut.window)) == cut.boundaries
