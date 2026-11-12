"""Hub'Eau helpers the station providers share.

A station is kept when its active dates overlap the requested window, and the
nearest located station of a list is kept. Coordinates come as degrees.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from hydromodpy.data.common.clients.hubeau import (
    keep_nearest,
    station_location,
    station_period_overlaps,
)

WINDOW = (datetime(2020, 1, 1), datetime(2020, 12, 31))

OVERLAPS = [
    pytest.param("2015-01-01", "2021-12-31", True, id="active over the window"),
    pytest.param("2015-01-01", "2018-12-31", False, id="closed before the window"),
    pytest.param("2022-01-01", None, False, id="opened after the window"),
    pytest.param(None, None, True, id="no dates"),
    pytest.param("not a date", "2019-12-31", False, id="start does not parse"),
    pytest.param("2021-02-01", "garbage", False, id="end does not parse"),
    pytest.param("garbage", "garbage", True, id="no date parses"),
]


@pytest.mark.parametrize(("start", "end", "overlaps"), OVERLAPS)
def test_station_period_overlaps(start, end, overlaps):
    assert bool(station_period_overlaps(start, end, *WINDOW)) is overlaps


def test_no_located_station_keeps_nothing():
    assert keep_nearest(["a", "b"], (0.0, 0.0), lambda _id: None, label="test") == []


NO_COORDINATES = [
    pytest.param(None, id="no payload"),
    pytest.param({}, id="empty payload"),
    pytest.param({"data": []}, id="no data"),
    pytest.param({"data": [{"lon": None, "lat": 48.0}]}, id="longitude is null"),
    pytest.param({"data": [{"lon": 1.0}]}, id="latitude absent"),
]


@pytest.mark.parametrize("payload", NO_COORDINATES)
def test_station_location_is_none_without_coordinates(payload):
    location = station_location(
        "S1",
        payload,
        lon_key="lon",
        lat_key="lat",
        metadata=lambda info: {"name": info.get("name")},
    )

    assert location is None
