"""Read BD Topage layers from the Sandre WFS over a Lambert-93 box.

The one place that speaks HTTP to the Sandre. Every rule below was measured
against the live service on 2026-09-27 (MapServer, WFS 2.0.0); the notes of
that survey list fourteen behaviours, four of which return a wrong answer
with no error. This module makes those four unreachable:

- A box is always sent in EPSG:2154 **with** ``SRSNAME`` in the same CRS. A
  Lambert-93 box without ``SRSNAME`` is widened to its WGS84 envelope (3 563
  reaches instead of 3 137 on the upper Ille), and a WGS84 box is read in
  lat,lon order whatever its suffix says. No attribute ``FILTER`` is ever sent:
  combined with ``SRSNAME`` it returns zero features and a valid response.
- Pages come back short: a ``COUNT=2000`` page holds 1 832 features while more
  remain, because the server pages over index candidates and drops the ones
  that miss the box afterwards. So ``STARTINDEX`` moves by ``COUNT``, never by
  what was received, and the loop stops on the total a ``hits`` request
  announced, never on a short page. The old loop stopped on the first short
  page and truncated any box holding more than one page.
- The ``GPKG`` output is a zip whose single member is literally named
  ``%TYPENAME%.gpkg``. It is read in memory, whatever its name.
- A refusal arrives as an ``ows:ExceptionReport``, as a MapServer HTML page,
  or as a valid empty answer. The first two are recognised by their body,
  whatever the HTTP status; the third is what the ``hits`` total guards.

The service holds the metropolitan layers only in Lambert-93 terms here: an
overseas layer (``_GLP_``, ``_MTQ_``, ``_MYT_``, ``_REU_``) is refused rather
than asked over a box that does not describe it.
"""

from __future__ import annotations

import io
import re
import warnings
import zipfile
from typing import TYPE_CHECKING, Final

from hydromodpy.core.exceptions import DataRequestError, DataSourceError
from hydromodpy.core.io.http_client import get_default_client
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd
    import requests

logger = get_logger(__name__)

SANDRE_WFS_URL: Final = "https://services.sandre.eaufrance.fr/geo/sandre"
SANDRE_WFS_HOST: Final = "services.sandre.eaufrance.fr"

QUERY_CRS: Final = "EPSG:2154"
"""The CRS every box is sent in and every feature comes back in."""

_QUERY_CRS_URN: Final = "urn:ogc:def:crs:EPSG::2154"

REQUEST_TIMEOUT_S: Final = 300.0
"""Per request, in seconds. A ``hits`` count over the Brittany reaches took 17.5 s."""

_MAX_EMPTY_PAGES: Final = 3
"""Consecutive empty pages tolerated before the total is declared unreachable.

A page of candidates that all miss the box comes back empty while features
remain behind it. None was observed, so this only bounds the loop.
"""

_OVERSEAS = re.compile(r"_(GLP|MTQ|MYT|REU)_")
_NUMBER_MATCHED = re.compile(rb'numberMatched="(\d+)"')


def require_metropolitan(typename: str) -> None:
    """Refuse a layer whose features a Lambert-93 box cannot describe."""
    match = _OVERSEAS.search(typename)
    if match is not None:
        raise DataRequestError(
            f"BD Topage layer {typename!r} covers {match.group(1)}, an overseas territory. "
            "This source asks the Sandre over a Lambert-93 (EPSG:2154) box, which covers "
            "metropolitan France only; use a *_FXX_* layer or a France-wide one."
        )


def bbox_params(typename: str, bbox: tuple[float, float, float, float]) -> dict[str, str]:
    """The only way this module builds a box query: ``BBOX`` and ``SRSNAME`` together.

    *bbox* is ``(xmin, ymin, xmax, ymax)`` in EPSG:2154, metres.
    """
    require_metropolitan(typename)
    xmin, ymin, xmax, ymax = (float(value) for value in bbox)
    return {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "BBOX": f"{xmin!r},{ymin!r},{xmax!r},{ymax!r},{_QUERY_CRS_URN}",
        "SRSNAME": _QUERY_CRS_URN,
    }


def count_features(typename: str, bbox: tuple[float, float, float, float]) -> int:
    """How many features of *typename* touch *bbox*, as the server counts them."""
    params = {**bbox_params(typename, bbox), "RESULTTYPE": "hits"}
    body = _checked_body(_get(params), typename=typename)
    match = _NUMBER_MATCHED.search(body[:4096])
    if match is None:
        raise DataSourceError(
            f"Sandre WFS answered a hits request on {typename!r} without numberMatched: "
            f"{_excerpt(body)}"
        )
    return int(match.group(1))


def get_features(
    typename: str,
    bbox: tuple[float, float, float, float],
    *,
    page_size: int,
) -> gpd.GeoDataFrame:
    """Every feature of *typename* touching *bbox*, in EPSG:2154.

    Features are whole: a reach crossing the box edge comes back entire, and
    cutting it to a shape is the caller's business. Empty text fields are
    ``None``, as the server writes a missing string as ``''``.

    Raises
    ------
    DataSourceError
        When the server refuses a request, or when the pages do not add up to
        the total it announced, or repeat a feature.
    """
    import geopandas as gpd
    import pandas as pd

    expected = count_features(typename, bbox)
    logger.info("[WFS] Sandre %s: %d features in the box", typename, expected)
    if expected == 0:
        return gpd.GeoDataFrame(geometry=[], crs=QUERY_CRS)

    frames: list[gpd.GeoDataFrame] = []
    received = 0
    start = 0
    empty_run = 0
    while received < expected:
        page = _get_page(typename, bbox, start=start, count=page_size)
        logger.debug("[WFS] %s STARTINDEX=%d: %d features", typename, start, len(page))
        if len(page):
            frames.append(page)
            received += len(page)
            empty_run = 0
        else:
            empty_run += 1
            if empty_run >= _MAX_EMPTY_PAGES:
                break
        start += page_size

    if received != expected:
        raise DataSourceError(
            f"Sandre WFS announced {expected} features of {typename!r} in the box and "
            f"{received} arrived over {start // page_size} pages of {page_size}. The layer "
            "may have been republished between the count and the pages; ask again."
        )
    frame = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs=frames[0].crs)
    if "gid" in frame.columns and frame["gid"].duplicated().any():
        raise DataSourceError(
            f"Sandre WFS repeated {int(frame['gid'].duplicated().sum())} features of "
            f"{typename!r} across pages; the paging was not stable, ask again."
        )
    if frame.crs is None:
        frame = frame.set_crs(QUERY_CRS)
    return empty_text_as_missing(frame)


def empty_text_as_missing(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Replace the ``''`` the server writes for a missing string by ``None``."""
    for column in frame.columns:
        if column == frame.geometry.name or frame[column].dtype != object:
            continue
        values = frame[column]
        blank = values.map(lambda value: isinstance(value, str) and value == "")
        if blank.any():
            frame[column] = values.astype(object).where(~blank, None)
    return frame


def _get_page(
    typename: str,
    bbox: tuple[float, float, float, float],
    *,
    start: int,
    count: int,
) -> gpd.GeoDataFrame:
    import geopandas as gpd

    params = {
        **bbox_params(typename, bbox),
        "COUNT": str(count),
        "STARTINDEX": str(start),
        "SORTBY": "gid",
        "OUTPUTFORMAT": "GPKG",
    }
    body = _checked_body(_get(params), typename=typename)
    if not body.startswith(b"PK"):
        raise DataSourceError(
            f"Sandre WFS answered a GPKG page of {typename!r} with something that is not "
            f"a zip archive: {_excerpt(body)}"
        )
    with zipfile.ZipFile(io.BytesIO(body)) as archive:
        members = archive.namelist()
        if not members:
            raise DataSourceError(f"Sandre WFS sent an empty zip for {typename!r}.")
        # The member is literally named "%TYPENAME%.gpkg": take it whatever its name.
        payload = archive.read(members[0])
    with warnings.catch_warnings():
        # GDAL reads the bytes under a /vsimem/ name with no .gpkg suffix and says so.
        warnings.filterwarnings("ignore", message=".*non conformant file extension")
        return gpd.read_file(io.BytesIO(payload))


def _get(params: dict[str, str]) -> requests.Response:
    return get_default_client().get(SANDRE_WFS_URL, params=params, timeout=REQUEST_TIMEOUT_S)


def _checked_body(response: requests.Response, *, typename: str) -> bytes:
    """The body of *response*, or the refusal it carries raised by name."""
    body = response.content or b""
    head = body[:4096]
    if b"ExceptionReport" in head or b"MapServer Message" in head:
        raise DataSourceError(f"Sandre WFS refused a request on {typename!r}: {_excerpt(body)}")
    status = getattr(response, "status_code", 200)
    if isinstance(status, int) and status >= 400:
        raise DataSourceError(
            f"Sandre WFS answered HTTP {status} on {typename!r}: {_excerpt(body)}"
        )
    return body


def _excerpt(body: bytes, limit: int = 300) -> str:
    """The readable text of *body*, markup removed, at most *limit* characters."""
    text = body[:8192].decode("utf-8", "replace")
    words = " ".join(re.sub(r"<[^>]*>?", " ", text).split())
    return words[:limit] or "<empty body>"


__all__ = [
    "QUERY_CRS",
    "REQUEST_TIMEOUT_S",
    "SANDRE_WFS_HOST",
    "SANDRE_WFS_URL",
    "bbox_params",
    "count_features",
    "empty_text_as_missing",
    "get_features",
    "require_metropolitan",
]
