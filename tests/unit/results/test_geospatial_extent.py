"""What a run may claim about where it is, in degrees.

``geospatial_lat/lon_*`` is WGS84 degrees by ACDD definition, and both writers
of a run used to put the native projected extent there. The positive cases live
here rather than in the characterization tier: the project that tier runs is a
synthetic aquifer numbered from the origin in metres, which declares no extent
at all, so it could never prove that a real one comes out right.
"""

from __future__ import annotations

import pytest

from hydromodpy.results.catalog.writes_helpers import wgs84_bounds

# A real catchment of the corpus, in Lambert-93.
_NANCON_L93 = (319987.5, 6776662.5, 330000.0, 6790000.0)


def test_a_projected_catchment_comes_out_in_degrees() -> None:
    bounds = wgs84_bounds(_NANCON_L93, "EPSG:2154")
    assert bounds is not None
    assert -2.2 < bounds["lon_min"] < bounds["lon_max"] < -1.9
    assert 47.9 < bounds["lat_min"] < bounds["lat_max"] < 48.2


def test_an_extent_already_in_degrees_is_unchanged() -> None:
    assert wgs84_bounds((-2.0, 48.0, -1.0, 49.0), "EPSG:4326") == {
        "lon_min": -2.0,
        "lon_max": -1.0,
        "lat_min": 48.0,
        "lat_max": 49.0,
    }


def test_a_geographic_crs_on_another_meridian_is_still_transformed() -> None:
    """NTF (Paris) is geographic and is not WGS84: its zero is Paris, not Greenwich."""
    bounds = wgs84_bounds((0.0, 50.0, 1.0, 51.0), "EPSG:4807")
    assert bounds is not None
    assert bounds["lon_min"] > 2.0, "the Paris meridian offset was not applied"


def test_an_inverted_bbox_is_normalised() -> None:
    xmin, ymin, xmax, ymax = _NANCON_L93
    assert wgs84_bounds((xmax, ymax, xmin, ymin), "EPSG:2154") == wgs84_bounds(
        _NANCON_L93, "EPSG:2154"
    )


@pytest.mark.parametrize(
    ("bbox", "crs", "why"),
    [
        (None, "EPSG:2154", "no extent"),
        (_NANCON_L93, None, "no projection"),
        ((0.0, 0.0, 400.0, 50.0), "EPSG:2154", "a synthetic grid numbered from the origin"),
        ((None, 0.0, 1.0, 1.0), "EPSG:2154", "a missing coordinate"),
        ((float("nan"), 0.0, 1.0, 1.0), "EPSG:2154", "a coordinate that is not a number"),
        (
            (0.0, 0.0, 400.0, 50.0),
            "+proj=tmerc +lat_0=0 +lon_0=0 +datum=WGS84 +units=m +no_defs",
            "a projection that declares no area of use",
        ),
        ((200000.0, 5000000.0, 800000.0, 5100000.0), "EPSG:32660", "an antimeridian crossing"),
        (_NANCON_L93, "not a crs at all", "an unparseable projection"),
    ],
)
def test_a_doubtful_extent_is_not_declared(bbox, crs, why) -> None:
    assert wgs84_bounds(bbox, crs) is None, f"declared an extent despite {why}"
