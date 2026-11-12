"""The two helpers the Hub'Eau providers share: period overlap and nearest station."""

from __future__ import annotations

from datetime import datetime

from hydromodpy.data.common.clients.hubeau import keep_nearest, station_period_overlaps

WINDOW = (datetime(2020, 1, 1), datetime(2020, 12, 31))


def test_a_date_that_does_not_parse_says_nothing() -> None:
    assert station_period_overlaps("not a date", "2019-12-31", *WINDOW) is False
    assert station_period_overlaps("2021-02-01", "garbage", *WINDOW) is False
    assert station_period_overlaps("garbage", "garbage", *WINDOW) is True


def test_no_located_station_keeps_nothing() -> None:
    assert keep_nearest(["a", "b"], (0.0, 0.0), lambda _id: None, label="test") == []
