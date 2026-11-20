"""A calendar instant a TOML file writes: a date, a datetime or an ISO 8601 string, nothing else."""

from __future__ import annotations

import datetime as dt

import pytest

from hydromodpy.core.time.instant import calendar_instant

pytestmark = pytest.mark.fast

READ = [
    pytest.param(dt.date(2003, 1, 1), dt.datetime(2003, 1, 1), id="TOML date"),
    pytest.param(dt.datetime(2003, 1, 1, 6), dt.datetime(2003, 1, 1, 6), id="TOML datetime"),
    pytest.param("2003-01-01", dt.datetime(2003, 1, 1), id="ISO date"),
    pytest.param("2003-01-01 06:00:00", dt.datetime(2003, 1, 1, 6), id="ISO with a space"),
    pytest.param("20030201", dt.datetime(2003, 2, 1), id="ISO basic"),
    pytest.param(
        "2003-01-01T00:00:00+01:00",
        dt.datetime(2003, 1, 1, tzinfo=dt.timezone(dt.timedelta(hours=1))),
        id="ISO with an offset",
    ),
]


@pytest.mark.parametrize(("value", "expected"), READ)
def test_a_calendar_instant_reads(value, expected) -> None:
    assert calendar_instant(value, "start") == expected


# A parser would take a number for seconds since 1970, and "01/02/2003" for 2 January.
REFUSED = [
    pytest.param(2003, id="number"),
    pytest.param(2003.0, id="float"),
    pytest.param(True, id="boolean"),
    pytest.param("2003", id="year alone"),
    pytest.param("01/02/2003", id="day and month order"),
    pytest.param("not a date", id="words"),
]


@pytest.mark.parametrize("value", REFUSED)
def test_anything_else_is_refused(value) -> None:
    with pytest.raises(ValueError, match="start = .* is not a date; write an ISO 8601 date"):
        calendar_instant(value, "start")
