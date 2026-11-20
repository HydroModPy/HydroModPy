"""What a run may claim about where it is, in degrees.

``geospatial_lat/lon_*`` is WGS84 degrees by ACDD definition, and both writers
of a run used to put the native projected extent there. The positive cases live
here rather than in the characterization tier: the project that tier runs is a
synthetic aquifer numbered from the origin in meters, which declares no extent
at all, so it could never prove that a real one comes out right.
"""

from __future__ import annotations

import pytest

from hydromodpy.results.storage.geo_metadata import wgs84_bounds

# A real catchment of the corpus, in Lambert-93.
_NANCON_L93 = (319987.5, 6776662.5, 330000.0, 6790000.0)


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
