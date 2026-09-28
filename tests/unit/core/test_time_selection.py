"""A date a user writes resolves to the stress period that holds it.

Period ``i`` is ``[edges[i], edges[i + 1])``, the convention the solvers and
``core/time/period_aggregation.py`` share. These tests pin the resolver the
figures and the exports read a date through.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.time import (
    ResolvedSteadySimulationTimeGrid,
    TimeSelectionError,
    grid_edges,
    period_label,
    resolve_instant,
    resolve_instants,
    resolve_period,
    resolve_simulation_time_grid,
)

MONTHLY = pd.date_range("2000-01-01", "2003-01-01", freq="MS")
DAILY = pd.date_range("2000-01-01", "2003-01-01", freq="D")
STEADY = pd.DatetimeIndex(["2000-01-01", "2003-01-01"])


def _grid(step_unit: str, *, step_value: int = 1):
    cfg = SimpleNamespace(
        simulation=SimpleNamespace(
            time=SimpleNamespace(
                mode="explicit",
                start_datetime="2000-01-01",
                end_datetime="2002-12-31",
                step_value=step_value,
                step_unit=step_unit,
                coverage_policy="ignore",
            ),
            process=[SimpleNamespace(type="flow", solvers=["modflow6"])],
        ),
        flow=SimpleNamespace(flow_regime="transient"),
    )
    return resolve_simulation_time_grid(cfg)


def test_a_date_inside_a_period_resolves_to_that_period() -> None:
    assert resolve_instant("2002-10-15", MONTHLY) == 33
    assert resolve_instant("2002-10-15", DAILY) == 1018
    assert resolve_instant("2000-01-31T23:00", MONTHLY) == 0


def test_a_date_on_an_edge_opens_the_period_it_starts() -> None:
    assert resolve_instant("2002-10-01", MONTHLY) == 33
    assert resolve_instant("2002-09-30", MONTHLY) == 32


def test_the_last_edge_resolves_to_the_last_period() -> None:
    assert resolve_instant("2003-01-01", MONTHLY) == 35
    assert resolve_instant("2003-01-01", DAILY) == len(DAILY) - 2


@pytest.mark.parametrize("date", ["1999-12-31", "2003-01-02"])
def test_a_date_outside_the_record_is_refused_with_the_span(date: str) -> None:
    with pytest.raises(TimeSelectionError, match="outside the record") as caught:
        resolve_instant(date, MONTHLY)
    assert "2000-01-01 to 2003-01-01" in str(caught.value)
    assert isinstance(caught.value, ValueError)


def test_first_last_and_indexes() -> None:
    assert resolve_instant("first", MONTHLY) == 0
    assert resolve_instant("LAST", MONTHLY) == 35
    assert resolve_instant(3, MONTHLY) == 3
    assert resolve_instant(-1, MONTHLY) == 35
    assert resolve_instant(np.int64(-36), MONTHLY) == 0
    with pytest.raises(TimeSelectionError, match="out of range"):
        resolve_instant(36, MONTHLY)
    with pytest.raises(TimeSelectionError, match="out of range"):
        resolve_instant(-37, MONTHLY)


def test_a_toml_date_and_a_timestamp_are_dates() -> None:
    assert resolve_instant(dt.date(2002, 10, 15), MONTHLY) == 33
    assert resolve_instant(dt.datetime(2002, 10, 15, 12), MONTHLY) == 33
    assert resolve_instant(pd.Timestamp("2002-10-15"), MONTHLY) == 33
    assert resolve_instant(np.datetime64("2002-10-15"), MONTHLY) == 33


def test_an_offset_date_is_read_in_utc() -> None:
    # 2002-10-01T00:30+01:00 is 2002-09-30T23:30 UTC, still September.
    assert resolve_instant("2002-10-01T00:30+01:00", MONTHLY) == 32


@pytest.mark.parametrize("value", ["", "now", "today", "abc", "nat", True, 1.5, None, [1]])
def test_anything_else_is_refused(value: object) -> None:
    with pytest.raises(TimeSelectionError, match="is not a date"):
        resolve_instant(value, MONTHLY)


def test_one_steady_period_takes_every_date_of_its_window() -> None:
    for date in ("2000-01-01", "2001-06-15", "2002-12-31", "2003-01-01"):
        assert resolve_instant(date, STEADY) == 0
    assert resolve_instant("last", STEADY) == 0
    with pytest.raises(TimeSelectionError, match="outside the record"):
        resolve_instant("2003-02-01", STEADY)


def test_a_run_without_dates_takes_first_last_and_its_one_index() -> None:
    for selector in ("first", "last", 0, -1):
        assert resolve_instant(selector, None) == 0
    with pytest.raises(TimeSelectionError, match='this run has no dates; write "last"'):
        resolve_instant("2002-10-15", None)
    with pytest.raises(TimeSelectionError, match="out of range"):
        resolve_instant(1, None)


def test_a_daily_and_a_monthly_grid_name_the_same_month() -> None:
    monthly = grid_edges(_grid("month"))
    daily = grid_edges(_grid("day"))
    for date in ("2000-02-29", "2001-07-04", "2002-10-15", "2002-12-31"):
        month = resolve_instant(date, monthly)
        day = resolve_instant(date, daily)
        assert monthly[month] <= daily[day] < daily[day + 1] <= monthly[month + 1]
        assert period_label(day, daily) == date
        assert period_label(month, monthly) == date[:7]


def test_n_periods_is_checked_against_the_edges() -> None:
    assert resolve_instant("last", MONTHLY, n_periods=36) == 35
    with pytest.raises(ValueError, match="36 periods, not 12"):
        resolve_instant("last", MONTHLY, n_periods=12)


def test_edges_must_increase() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        resolve_instant("first", ["2001-01-01", "2000-01-01"])
    with pytest.raises(ValueError, match="at least two edges"):
        resolve_instant("first", ["2001-01-01"])


def test_resolve_instants_keeps_the_order_given() -> None:
    assert resolve_instants(["2002-10-15", "first", -1], MONTHLY) == (33, 0, 35)
    assert resolve_instants("2002-10-15", MONTHLY) == (33,)
    assert resolve_instants((), MONTHLY) == ()


def test_resolve_period_keeps_every_overlapping_period() -> None:
    assert resolve_period("2002-10-15", "2002-12-01", MONTHLY) == (33, 34, 35)
    assert resolve_period("2002-10-01", "2002-10-31", MONTHLY) == (33,)
    assert resolve_period("first", "2000-03-01", MONTHLY) == (0, 1, 2)
    assert resolve_period("2002-11-15", "last", MONTHLY) == (34, 35)
    assert resolve_period(0, -1, STEADY) == (0,)
    assert resolve_period("2001-01-01", "2001-12-31", STEADY) == (0,)


def test_resolve_period_clips_a_window_that_runs_past_the_record() -> None:
    assert resolve_period("1999-06-01", "2000-02-15", MONTHLY) == (0, 1)
    assert resolve_period("2002-11-15", "2010-01-01", MONTHLY) == (34, 35)


def test_resolve_period_refuses_an_empty_window() -> None:
    with pytest.raises(TimeSelectionError, match="outside the record"):
        resolve_period("2004-01-01", "2005-01-01", MONTHLY)
    with pytest.raises(TimeSelectionError, match="outside the record"):
        resolve_period("1990-01-01", "1991-01-01", MONTHLY)
    with pytest.raises(TimeSelectionError, match="ends before it starts"):
        resolve_period("2002-10-15", "2001-01-01", MONTHLY)
    with pytest.raises(TimeSelectionError, match="this run has no dates"):
        resolve_period("2002-10-15", "last", None)
    assert resolve_period("first", "last", None) == (0,)


def test_period_labels() -> None:
    assert period_label(33, MONTHLY) == "2002-10"
    assert period_label(-1, MONTHLY) == "2002-12"
    assert period_label(1018, DAILY) == "2002-10-15"
    assert period_label(0, STEADY) == "2000-01-01 to 2002-12-31"
    assert period_label(0, pd.DatetimeIndex(["2001-01-01", "2002-01-01"])) == "2001"
    assert period_label(0, pd.DatetimeIndex(["2001-01-15", "2001-02-15"])) == (
        "2001-01-15 to 2001-02-14"
    )
    hourly = pd.DatetimeIndex(["2001-01-01 06:00", "2001-01-01 07:00"])
    assert period_label(0, hourly) == "2001-01-01 06:00 to 2001-01-01 07:00"
    assert period_label(0, None) == ""
    with pytest.raises(TimeSelectionError, match="out of range"):
        period_label(36, MONTHLY)


def test_grid_edges_reads_the_boundaries() -> None:
    grid = _grid("month")
    edges = grid_edges(grid)
    assert list(edges) == list(MONTHLY)
    assert len(edges) == grid.nper + 1
    assert grid_edges(ResolvedSteadySimulationTimeGrid()) is None
    assert grid_edges(None) is None


def test_a_steady_window_grid_has_one_period_over_the_record() -> None:
    # What calibration's steady regime writes: one period as long as the window.
    edges = grid_edges(_grid("day", step_value=1096))
    assert list(edges) == list(STEADY)
    assert resolve_instant("2002-10-15", edges) == 0
    assert period_label(0, edges) == "2000-01-01 to 2002-12-31"
