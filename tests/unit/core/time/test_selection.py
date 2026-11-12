"""A date a user writes resolves to the stress period that holds it.

Period ``i`` is ``[edges[i], edges[i + 1])``, the convention the solvers and
``core/time/period_aggregation.py`` share. These tests pin the resolver the
figures and the exports read a date through.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest

from hydromodpy.core.time.selection import (
    TimeSelectionError,
    grid_edges,
    in_series_window,
    period_label,
    resolve_instant,
    resolve_period,
)
from hydromodpy.core.time.window import resolve_simulation_time_grid

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


@pytest.mark.parametrize("value", ["", "now", "today", "abc", "nat", True, 1.5, None, [1]])
def test_anything_else_is_refused(value: object) -> None:
    with pytest.raises(TimeSelectionError, match="is not a date"):
        resolve_instant(value, MONTHLY)


def test_n_periods_is_checked_against_the_edges() -> None:
    assert resolve_instant("last", MONTHLY, n_periods=36) == 35
    with pytest.raises(ValueError, match="36 periods, not 12"):
        resolve_instant("last", MONTHLY, n_periods=12)


def test_edges_must_increase() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        resolve_instant("first", ["2001-01-01", "2000-01-01"])
    with pytest.raises(ValueError, match="at least two edges"):
        resolve_instant("first", ["2001-01-01"])


def test_resolve_period_keeps_every_overlapping_period() -> None:
    assert resolve_period("2002-10-15", "2002-12-02", MONTHLY) == (33, 34, 35)
    assert resolve_period("2002-10-01", "2002-10-31", MONTHLY) == (33,)
    assert resolve_period("first", "2000-03-02", MONTHLY) == (0, 1, 2)
    assert resolve_period("2002-11-15", "last", MONTHLY) == (34, 35)
    assert resolve_period(0, -1, STEADY) == (0,)
    assert resolve_period("2001-01-01", "2001-12-31", STEADY) == (0,)


@pytest.mark.parametrize(
    "window",
    [("2003-01-01", "2010-01-01"), ("2003-01-01", "last"), ("1999-01-01", "2000-01-01")],
)
def test_a_window_that_only_touches_the_record_holds_no_period(window: tuple) -> None:
    with pytest.raises(TimeSelectionError, match="outside the record"):
        resolve_period(*window, MONTHLY)


def _kept(period: object, *, observed: bool, edges: object = None) -> list[str]:
    times = pd.date_range("2003-01-01", "2003-04-01", freq="MS")
    kept = times[in_series_window(times, observed=observed, period=period, edges=edges)]
    return kept.strftime("%m-%d").tolist()


@pytest.mark.parametrize(
    ("window", "simulated", "measured"),
    [
        (("2003-02-01", "2003-03-01"), ["03-01"], ["02-01"]),
        (("2003-02-15", "2003-02-20"), ["03-01"], ["02-01"]),
        (("2003-01-01", "2003-02-01"), ["02-01"], ["01-01"]),
        (("2003-01-01", "2003-01-01"), ["02-01"], ["01-01"]),
        (("2003-02-01", "2003-02-01"), ["02-01"], ["01-01"]),
        (("2003-04-01", "2003-04-01"), ["04-01"], ["03-01"]),
        (("2002-01-01", "2010-01-01"), ["02-01", "03-01", "04-01"], ["01-01", "02-01", "03-01"]),
        ("2003", ["02-01", "03-01", "04-01"], ["01-01", "02-01", "03-01"]),
    ],
)
def test_a_window_over_a_series_keeps_the_periods_it_overlaps(window, simulated, measured) -> None:
    edges = pd.date_range("2003-01-01", "2003-04-01", freq="MS")

    assert _kept(window, observed=False, edges=edges) == simulated
    assert _kept(window, observed=True, edges=edges) == measured


def test_a_window_on_a_run_without_edges_reads_its_two_bounds() -> None:
    assert _kept(("2003-02-01", "2003-03-01"), observed=False) == ["03-01"]
    assert _kept(("2003-02-01", "2003-03-01"), observed=True) == ["02-01"]
    with pytest.raises(TimeSelectionError, match="this run has no dates"):
        _kept(("2003-02-01", "2003-02-01"), observed=False)
    with pytest.raises(TimeSelectionError, match="ends before it starts"):
        _kept(("2003-03-01", "2003-02-01"), observed=False)
    with pytest.raises(TimeSelectionError, match="not a year"):
        _kept("two thousand", observed=False)


def test_a_window_over_a_series_reads_its_bounds_and_its_stamps_in_utc() -> None:
    paris = dt.timezone(dt.timedelta(hours=1))
    times = pd.DatetimeIndex(["2020-01-01", "2020-01-02"], tz="UTC")
    window = (dt.datetime(2020, 1, 1, 1, tzinfo=paris), dt.datetime(2020, 1, 2, 1, tzinfo=paris))

    assert in_series_window(times, observed=False, period=window).tolist() == [False, True]


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


def test_a_steady_window_grid_has_one_period_over_the_record() -> None:
    # What calibration's steady regime writes: one period as long as the window.
    edges = grid_edges(_grid("day", step_value=1096))
    assert list(edges) == list(STEADY)
    assert resolve_instant("2002-10-15", edges) == 0
    assert period_label(0, edges) == "2000-01-01 to 2002-12-31"
