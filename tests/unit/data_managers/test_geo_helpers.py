"""Tests for common/geo_helpers."""

import pytest

from hydromodpy.data_managers.common.geo_helpers import (
    bbox_contains,
    filter_locations_by_bbox,
    haversine_km,
    nearest_location,
)
from hydromodpy.data_managers.contracts.location import StationLocation


def _loc(id, x, y):
    return StationLocation(id=id, x=x, y=y, crs="EPSG:4326")


class TestBboxContains:
    def test_contains(self):
        assert bbox_contains((0, 0, 10, 10), (2, 2, 8, 8))

    def test_not_contains(self):
        assert not bbox_contains((0, 0, 10, 10), (5, 5, 15, 15))

    def test_equal(self):
        assert bbox_contains((0, 0, 10, 10), (0, 0, 10, 10))


class TestHaversine:
    def test_same_point(self):
        assert haversine_km(0, 0, 0, 0) == pytest.approx(0)

    def test_known_distance(self):
        # Paris (2.35, 48.86) to London (-0.12, 51.51) ≈ 344 km
        d = haversine_km(2.35, 48.86, -0.12, 51.51)
        assert 340 < d < 350


class TestFilterLocationsByBbox:
    def test_filter(self):
        locs = [_loc("A", 1, 1), _loc("B", 5, 5), _loc("C", 15, 15)]
        filtered = filter_locations_by_bbox(locs, (0, 0, 10, 10))
        assert len(filtered) == 2
        assert {l.id for l in filtered} == {"A", "B"}


class TestNearestLocation:
    def test_nearest(self):
        locs = [_loc("A", 0, 0), _loc("B", 1, 1), _loc("C", 10, 10)]
        nearest = nearest_location(0.5, 0.5, locs)
        assert nearest.id == "B"

    def test_empty(self):
        assert nearest_location(0, 0, []) is None
