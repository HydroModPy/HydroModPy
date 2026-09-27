"""A buffer declared as a distance reaches the domain as that distance.

``geographic.buff_area`` carries three meanings in one field, told apart by the
form the config validator writes: ``"10%"`` is an area increase, ``"10.0 m"``
a distance, a bare number the legacy v1 rule. The distance form once lost its
unit on the way and the parser refused the bare token it was left with, so the
distance form raised before it could be used.
"""

from __future__ import annotations

import pytest
from shapely.geometry import box

from hydromodpy.spatial.geographic.core.catchment_domain import _compute_buffer_distance
from hydromodpy.spatial.geographic.geographic_config import _normalize_buff_area

AREA_KM2 = 3.3
SIDE_M = (AREA_KM2 * 1.0e6) ** 0.5
CATCHMENT = box(0.0, 0.0, SIDE_M, SIDE_M)


def _distance(declared: object) -> float:
    return _compute_buffer_distance(
        catchment=CATCHMENT, buff_area=_normalize_buff_area(declared), dem_resolution=None
    )


@pytest.mark.parametrize(
    ("declared", "expected_m"),
    [("10 m", 10.0), ("500 m", 500.0), ("2 km", 2000.0), ("10.0", 10.0)],
)
def test_a_declared_distance_survives_normalization(declared: str, expected_m: float) -> None:
    normalized = _normalize_buff_area(declared)
    assert isinstance(normalized, str)
    assert _distance(declared) == expected_m


def test_a_bare_number_still_scales_with_the_square_root_of_the_area() -> None:
    normalized = _normalize_buff_area(10)
    assert isinstance(normalized, float)
    assert _distance(10) == pytest.approx(AREA_KM2**0.5 * 0.10 * 1000.0, abs=1.0)


def test_a_distance_and_a_percentage_do_not_collide() -> None:
    assert _distance("10 m") != _distance("10%")
