"""Unit tests for query period-bound normalization (UTC + half-open year)."""

from __future__ import annotations

import datetime as dt

from hydromodpy.results.derive.time_alignment import normalize_period_bounds

UTC = dt.UTC


def test_year_string_expands_to_half_open_utc_range():
    lo, hi, hi_inclusive = normalize_period_bounds("2020")
    # Half-open [2020-01-01, 2021-01-01): the old inclusive "2020-12-31" dropped
    # every sub-daily 31 December sample.
    assert hi_inclusive is False
    assert lo == dt.datetime(2020, 1, 1, tzinfo=UTC)
    assert hi == dt.datetime(2021, 1, 1, tzinfo=UTC)


def test_explicit_bounds_are_normalized_to_utc_and_stay_inclusive():
    lo, hi, hi_inclusive = normalize_period_bounds(("2020-01-01", "2020-06-30"))
    assert hi_inclusive is True
    assert lo.utcoffset() == dt.timedelta(0)
    assert hi.utcoffset() == dt.timedelta(0)
    assert lo == dt.datetime(2020, 1, 1, tzinfo=UTC)


def test_tz_aware_bounds_are_converted_not_relabeled():
    paris = dt.timezone(dt.timedelta(hours=1))
    lo, hi, _ = normalize_period_bounds(
        (dt.datetime(2020, 1, 1, 1, 0, tzinfo=paris), dt.datetime(2020, 1, 2, tzinfo=paris))
    )
    # 01:00+01:00 is 00:00 UTC, not relabeled to 01:00 UTC.
    assert lo == dt.datetime(2020, 1, 1, 0, 0, tzinfo=UTC)
