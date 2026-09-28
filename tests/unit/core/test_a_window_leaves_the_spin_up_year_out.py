"""A scoring window cuts the calendar years of a run to the years it holds whole.

The two-bound mode scores complete calendar years. A spin-up year, whose first
step starts from the initial condition, is one of them unless a window leaves
it out. A year is scored when the window starts on or before its 1 January and
ends on or after its 31 December.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from hydromodpy.core.stream_extent import calendar_years


def _daily_edges(first: str, last: str) -> np.ndarray:
    return np.arange(np.datetime64(first), np.datetime64(last), np.timedelta64(1, "D"))


DAILY = _daily_edges("2000-01-01", "2003-01-02")
"""1096 daily steps, 2000 to 2002, as example 04 runs."""


def test_without_a_window_every_complete_year_is_scored() -> None:
    years = calendar_years(DAILY)
    assert years.years == (2000, 2001, 2002)
    assert years.outside_window == ()


def test_the_spin_up_year_leaves_the_score() -> None:
    years = calendar_years(DAILY, window=("2001-01-01", "2002-12-31"))
    assert years.years == (2001, 2002)
    assert years.outside_window == (2000,)
    assert years.n_steps.tolist() == [365, 365]
    # The steps kept are those of the whole run: they index the release stack.
    assert int(years.steps[0][0]) == 366


def test_the_window_end_is_an_inclusive_date() -> None:
    assert calendar_years(DAILY, window=(None, "2001-12-31")).years == (2000, 2001)
    assert calendar_years(DAILY, window=(None, "2001-12-30")).years == (2000,)


def test_a_window_starting_after_1_january_drops_that_year() -> None:
    years = calendar_years(DAILY, window=("2000-01-02", None))
    assert years.years == (2001, 2002)
    assert years.outside_window == (2000,)


def test_an_open_window_changes_nothing() -> None:
    open_window = calendar_years(DAILY, window=(None, None))
    assert open_window.years == (2000, 2001, 2002)
    assert open_window.outside_window == ()


def test_timestamps_are_read_like_strings() -> None:
    window = (pd.Timestamp("2001-01-01"), pd.Timestamp("2002-12-31"))
    assert calendar_years(DAILY, window=window).years == (2001, 2002)


def test_an_incomplete_year_stays_incomplete_whatever_the_window() -> None:
    edges = _daily_edges("2000-03-01", "2003-01-02")
    years = calendar_years(edges, window=("2000-01-01", "2001-12-31"))
    assert years.years == (2001,)
    assert years.incomplete == (2000,)
    assert years.outside_window == (2002,)


def test_a_window_holding_no_whole_year_leaves_nothing() -> None:
    years = calendar_years(DAILY, window=("2001-02-01", "2001-11-30"))
    assert years.years == ()
    assert years.outside_window == (2000, 2001, 2002)


def test_a_reversed_window_is_refused() -> None:
    with pytest.raises(ValueError, match="after its end"):
        calendar_years(DAILY, window=("2002-01-01", "2001-01-01"))


def test_a_bound_that_is_no_date_is_refused() -> None:
    with pytest.raises(ValueError, match="not a date"):
        calendar_years(DAILY, window=("spring", None))
