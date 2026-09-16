"""A buffer declared as a distance reaches the domain as that distance.

``geographic.buff_area`` carries two meanings in one field: a number is a
percentage of the catchment size, a string is an explicit distance. The config
validator normalizes the distance form to metres and hands it back as a string,
which is what keeps the two apart. That leaves a token with no unit, and the
parser used to refuse it, so the distance form raised before it could be used.
"""

from __future__ import annotations

import pytest

from hydromodpy.spatial.geographic.core.catchment_domain import _compute_buffer_distance
from hydromodpy.spatial.geographic.geographic_config import _normalize_buff_area

AREA_KM2 = 3.3


@pytest.mark.parametrize(
    ("declared", "expected_m"),
    [("10 m", 10.0), ("500 m", 500.0), ("2 km", 2000.0)],
)
def test_a_declared_distance_survives_normalization(declared: str, expected_m: float) -> None:
    normalized = _normalize_buff_area(declared)
    assert isinstance(normalized, str)
    assert (
        _compute_buffer_distance(
            catchment_area_km2=AREA_KM2, buff_area=normalized, dem_resolution=None
        )
        == expected_m
    )


def test_a_declared_percentage_still_scales_with_the_catchment() -> None:
    normalized = _normalize_buff_area("10%")
    assert isinstance(normalized, float)
    scaled = _compute_buffer_distance(
        catchment_area_km2=AREA_KM2, buff_area=normalized, dem_resolution=None
    )
    assert scaled == pytest.approx(AREA_KM2**0.5 * 0.10 * 1000.0, abs=1.0)


def test_a_distance_and_a_percentage_do_not_collide() -> None:
    as_distance = _compute_buffer_distance(
        catchment_area_km2=AREA_KM2, buff_area=_normalize_buff_area("10 m"), dem_resolution=None
    )
    as_percent = _compute_buffer_distance(
        catchment_area_km2=AREA_KM2, buff_area=_normalize_buff_area("10%"), dem_resolution=None
    )
    assert as_distance != as_percent
