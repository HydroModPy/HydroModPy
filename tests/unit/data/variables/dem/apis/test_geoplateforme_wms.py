"""One WMS-Raster tile of the Geoplateforme: a 5 m grid of elevation in m, boxes in Lambert-93 m.

The session is canned. It answers a GeoTIFF, an XML error or a cut body for any box.
"""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from hydromodpy.data.variables.dem.apis import geoplateforme_wms as wms
from hydromodpy.data.variables.dem.apis.geoplateforme_download import GeoPlateformeDownloadError

pytestmark = pytest.mark.fast

FLUME = (344000.0, 6806000.0, 344200.0, 6806200.0)


class Answer:
    status_code = 200

    def __init__(self, content: bytes) -> None:
        self.content = content


class Session:
    """Answers each GetMap with ``serve(bbox, width, height)`` and counts them."""

    def __init__(self, serve: Callable[[tuple, int, int], bytes]) -> None:
        self.serve = serve
        self.requests: list[dict] = []

    def request(self, method, url, params=None, **_kwargs):
        self.requests.append(dict(params))
        bbox = tuple(float(v) for v in params["BBOX"].split(","))
        return Answer(self.serve(bbox, int(params["WIDTH"]), int(params["HEIGHT"])))


def geotiff(array: np.ndarray, bbox: tuple, nodata: float = -99999.0) -> bytes:
    height, width = array.shape
    res = (bbox[2] - bbox[0]) / width
    with MemoryFile() as memory:
        with memory.open(
            driver="GTiff",
            height=height,
            width=width,
            count=1,
            dtype="float32",
            crs="EPSG:2154",
            transform=from_origin(bbox[0], bbox[3], res, res),
            nodata=nodata,
        ) as dst:
            dst.write(array.astype("float32"), 1)
        return memory.read()


def first_tile():
    return next(wms.plan_tiles(FLUME, 5.0))


def test_oversized_tile_is_refused():
    with pytest.raises(ValueError, match="tile_px"):
        list(wms.plan_tiles(FLUME, 5.0, tile_px=wms.MAX_IMAGE_PX + 1))


def test_xml_error_with_status_200():
    session = Session(lambda *a: b'<?xml version="1.0"?><ServiceExceptionReport/>')

    with pytest.raises(GeoPlateformeDownloadError, match="did not answer a GeoTIFF"):
        wms.fetch_tile("LAYER", first_tile(), client=session)


def test_wrong_grid_size_is_refused():
    session = Session(lambda bbox, w, h: geotiff(np.ones((h - 1, w)), bbox))

    with pytest.raises(GeoPlateformeDownloadError, match="pixels"):
        wms.fetch_tile("LAYER", first_tile(), client=session)


def test_truncated_body_is_retried_once():
    good = geotiff(np.full((40, 40), 111.0), FLUME)
    bodies = [good[: len(good) // 2], good]
    session = Session(lambda *a: bodies.pop(0))

    data = wms.fetch_tile("LAYER", first_tile(), client=session)

    assert len(session.requests) == 2
    assert (data == 111.0).all()


def test_persistent_truncation_is_refused():
    good = geotiff(np.full((40, 40), 111.0), FLUME)
    session = Session(lambda *a: good[: len(good) // 2])

    with pytest.raises(GeoPlateformeDownloadError, match="cannot be read"):
        wms.fetch_tile("LAYER", first_tile(), client=session)
    assert len(session.requests) == 2
