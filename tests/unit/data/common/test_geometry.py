"""Distances (km) and boxes (degrees) of station geometry.

Haversine distance on a sphere of radius 6371 km. A box is
(xmin, ymin, xmax, ymax) and grows by a radius in km.
"""

import math

import pytest
from shapely.geometry import box

from hydromodpy.data.common.geometry import expand_bbox, geometry_to_bbox, haversine_km

DISTANCES = [
    pytest.param((0, 0, 0, 0), 0.0, 1e-9, id="same point"),
    # Paris (2.35, 48.86) to London (-0.12, 51.51) is about 344 km.
    pytest.param((2.35, 48.86, -0.12, 51.51), 344.0, 6.0, id="paris to london"),
    pytest.param((0.0, 0.0, 1.0, 0.0), 6371.0 * math.pi / 180.0, 1e-6, id="degree of equator"),
]


@pytest.mark.parametrize(("points", "km", "tolerance"), DISTANCES)
def test_haversine_km(points, km, tolerance):
    assert haversine_km(*points) == pytest.approx(km, abs=tolerance)


def test_geometry_to_bbox():
    bbox = geometry_to_bbox(box(-2.0, 47.0, -1.0, 49.0))

    assert bbox == pytest.approx((-2.0, 47.0, -1.0, 49.0))


def test_expand_bbox():
    expanded = expand_bbox((-1.0, 48.0, 0.0, 49.0), radius_km=50.0)

    assert expanded[0] < -1.0
    assert expanded[1] < 48.0
    assert expanded[2] > 0.0
    assert expanded[3] > 49.0
