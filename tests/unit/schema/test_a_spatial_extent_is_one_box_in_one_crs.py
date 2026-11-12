"""A job records its extent one way: a native box and the CRS it is in.

The inputset resource and the job seal used to take any mapping, and the
view read two spellings of it. These tests pin the one shape that is left,
and the refusals that keep a second one from coming back.
"""

from __future__ import annotations

import math

import pytest

from hydromodpy.schema.job.extent import SpatialExtent

pytestmark = pytest.mark.fast

NANCON_BBOX_L93 = (385087.5, 6814387.5, 396862.5, 6827287.5)


@pytest.mark.parametrize(
    "bbox",
    [
        (1.0, 2.0, 3.0),
        (1.0, 2.0, 3.0, 4.0, 5.0),
        "1,2,3,4",
        None,
        (0.0, 0.0, "1", 1.0),
        (0.0, 0.0, True, 1.0),
        (0.0, 0.0, math.nan, 1.0),
        (0.0, 0.0, math.inf, 1.0),
        (10.0, 0.0, 5.0, 1.0),
        (0.0, 10.0, 1.0, 5.0),
        (0.0, 0.0, 0.0, 1.0),
    ],
    ids=[
        "three",
        "five",
        "string",
        "none",
        "text-member",
        "boolean",
        "nan",
        "inf",
        "x-inverted",
        "y-inverted",
        "x-empty",
    ],
)
def test_a_box_that_is_not_four_ordered_finite_numbers_is_refused(bbox: object) -> None:
    with pytest.raises(ValueError, match="bbox"):
        SpatialExtent(bbox=bbox, crs="EPSG:2154")  # type: ignore[arg-type]


@pytest.mark.parametrize("crs", [None, "", "   ", 2154], ids=["none", "empty", "blank", "int"])
def test_an_extent_without_a_crs_string_is_refused(crs: object) -> None:
    with pytest.raises(ValueError, match="names none"):
        SpatialExtent(bbox=NANCON_BBOX_L93, crs=crs)  # type: ignore[arg-type]


def test_a_crs_pyproj_cannot_parse_is_refused() -> None:
    with pytest.raises(ValueError, match="cannot be parsed"):
        SpatialExtent(bbox=NANCON_BBOX_L93, crs="lambert93")


def test_a_document_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        SpatialExtent.from_document(list(NANCON_BBOX_L93))
