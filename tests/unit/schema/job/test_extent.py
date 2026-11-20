"""The extent of a job input: a native bounding box (x_min, y_min, x_max, y_max) and its CRS.

The inputset resource and the job seal take this one shape. A box must be four
finite numbers with positive width and height, and the CRS must parse.
"""

from __future__ import annotations

import math

import pytest

from hydromodpy.schema.job.extent import SpatialExtent

pytestmark = pytest.mark.fast

NANCON_BBOX_L93 = (385087.5, 6814387.5, 396862.5, 6827287.5)

BAD_BOXES = [
    pytest.param((1.0, 2.0, 3.0), id="three"),
    pytest.param((1.0, 2.0, 3.0, 4.0, 5.0), id="five"),
    pytest.param("1,2,3,4", id="string"),
    pytest.param(None, id="none"),
    pytest.param((0.0, 0.0, "1", 1.0), id="text-member"),
    pytest.param((0.0, 0.0, True, 1.0), id="boolean"),
    pytest.param((0.0, 0.0, math.nan, 1.0), id="nan"),
    pytest.param((0.0, 0.0, math.inf, 1.0), id="inf"),
    pytest.param((10.0, 0.0, 5.0, 1.0), id="x-inverted"),
    pytest.param((0.0, 10.0, 1.0, 5.0), id="y-inverted"),
    pytest.param((0.0, 0.0, 0.0, 1.0), id="x-empty"),
]


@pytest.mark.parametrize("bbox", BAD_BOXES)
def test_box_refusals(bbox: object) -> None:
    with pytest.raises(ValueError, match="bbox"):
        SpatialExtent(bbox=bbox, crs="EPSG:2154")  # type: ignore[arg-type]


BAD_CRS = [
    pytest.param(None, "names none", id="none"),
    pytest.param("", "names none", id="empty"),
    pytest.param("   ", "names none", id="blank"),
    pytest.param(2154, "names none", id="int"),
    pytest.param("lambert93", "cannot be parsed", id="unknown name"),
]


@pytest.mark.parametrize(("crs", "message"), BAD_CRS)
def test_crs_refusals(crs: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        SpatialExtent(bbox=NANCON_BBOX_L93, crs=crs)  # type: ignore[arg-type]


def test_document_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="JSON object"):
        SpatialExtent.from_document(list(NANCON_BBOX_L93))
