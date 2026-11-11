"""Tests for common/geometry."""

import math

import pytest

from hydromodpy.data.common.geometry import (
    haversine_km,
)
from hydromodpy.data.contracts.location import StationLocation


def _loc(id, x, y):
    return StationLocation(id=id, x=x, y=y, crs="EPSG:4326")


class TestHaversine:
    def test_same_point(self):
        assert haversine_km(0, 0, 0, 0) == pytest.approx(0)

    def test_known_distance(self):
        # Paris (2.35, 48.86) to London (-0.12, 51.51) ≈ 344 km
        d = haversine_km(2.35, 48.86, -0.12, 51.51)
        assert 340 < d < 350

    def test_one_degree_of_the_equator_is_a_great_circle_arc(self):
        assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(6371.0 * math.pi / 180.0)
