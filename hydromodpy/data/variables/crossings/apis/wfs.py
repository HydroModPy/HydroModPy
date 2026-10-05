"""Page through a WFS 2.0 layer over a Lambert-93 box.

Shared by the two network providers of the crossings variable. The rules come
from what the Sandre WFS was measured to do (see
:mod:`hydromodpy.data.common.clients.sandre_topage`), and the Geoplateforme
answers the same way to them:

- A box is sent with its CRS as a URN, and ``SRSNAME`` is sent in the same CRS.
- The total comes first, from a ``RESULTTYPE=hits`` request, and the loop ends
  on that total, never on a short page.
- ``STARTINDEX`` moves by ``COUNT``, never by what arrived.
- A page is sorted, so that the pages do not overlap.
- A refusal arrives as an ``ows:ExceptionReport`` whatever the HTTP status.

The pages are handed out one by one, so that a caller that writes each page as it
arrives holds one page in memory, however many features the box holds.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Hashable, Iterator
from typing import Final, TypeVar

from hydromodpy.core.exceptions import DataSourceError
from hydromodpy.core.io.http_client import get_default_client
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)

QUERY_CRS: Final = "EPSG:2154"
"""The CRS every box is sent in and every feature comes back in."""

_URN: Final = "urn:ogc:def:crs:EPSG::2154"
_TIMEOUT_S: Final = 120.0
_MAX_EMPTY_PAGES: Final = 3
_NUMBER_MATCHED = re.compile(rb'numberMatched="(\d+)"')

Feature = TypeVar("Feature")


def box_params(typename: str, bbox: tuple[float, float, float, float]) -> dict[str, str]:
    """``BBOX`` and ``SRSNAME`` together, *bbox* being ``(xmin, ymin, xmax, ymax)`` in EPSG:2154."""
    xmin, ymin, xmax, ymax = (float(value) for value in bbox)
    return {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "BBOX": f"{xmin!r},{ymin!r},{xmax!r},{ymax!r},{_URN}",
        "SRSNAME": _URN,
    }


def iter_pages(
    url: str,
    typename: str,
    bbox: tuple[float, float, float, float],
    *,
    page_size: int,
    sort_by: str,
    parse_page: Callable[[bytes], list[Feature]],
    identify: Callable[[Feature], Hashable],
    output_format: str | None = None,
    properties: tuple[str, ...] | None = None,
) -> Iterator[list[Feature]]:
    """The features of *typename* touching *bbox*, one page at a time, as *parse_page* reads them.

    *properties* limits the attributes the server sends (``PROPERTYNAME``), which
    is what keeps a page small when only a few of them are read.

    Raises
    ------
    DataSourceError
        When the server refuses a request, when a feature comes twice, or when
        the pages do not add up to the total it announced (raised once the last
        page has been handed out).
    """
    expected = _count(url, typename, bbox)
    logger.info("[WFS] %s: %d features in the box", typename, expected)
    if expected == 0:
        return

    seen: set[Hashable] = set()
    start = 0
    empty_run = 0
    while len(seen) < expected:
        extra = {"COUNT": str(page_size), "STARTINDEX": str(start), "SORTBY": sort_by}
        if output_format is not None:
            extra["outputFormat"] = output_format
        if properties is not None:
            extra["PROPERTYNAME"] = ",".join(properties)
        page = parse_page(_get(url, {**box_params(typename, bbox), **extra}, typename))
        logger.debug("[WFS] %s STARTINDEX=%d: %d features", typename, start, len(page))
        if page:
            keys = [identify(feature) for feature in page]
            repeated = len(keys) - len(set(keys) - seen)
            if repeated:
                raise DataSourceError(
                    f"WFS repeated {repeated} features of {typename!r} across "
                    "pages; the paging was not stable, ask again."
                )
            seen.update(keys)
            empty_run = 0
            yield page
        else:
            empty_run += 1
            if empty_run >= _MAX_EMPTY_PAGES:
                break
        start += page_size

    if len(seen) != expected:
        raise DataSourceError(
            f"WFS announced {expected} features of {typename!r} in the box and "
            f"{len(seen)} arrived. The layer may have been republished between the "
            "count and the pages; ask again."
        )


def _count(url: str, typename: str, bbox: tuple[float, float, float, float]) -> int:
    body = _get(url, {**box_params(typename, bbox), "RESULTTYPE": "hits"}, typename)
    match = _NUMBER_MATCHED.search(body[:4096])
    if match is None:
        raise DataSourceError(
            f"WFS answered a hits request on {typename!r} without numberMatched: {_excerpt(body)}"
        )
    return int(match.group(1))


def _get(url: str, params: dict[str, str], typename: str) -> bytes:
    """The body of one answer, or the refusal it carries raised by name."""
    response = get_default_client().get(url, params=params, timeout=_TIMEOUT_S)
    body = response.content or b""
    head = body[:4096]
    if b"ExceptionReport" in head or b"MapServer Message" in head:
        raise DataSourceError(f"WFS refused a request on {typename!r}: {_excerpt(body)}")
    status = getattr(response, "status_code", 200)
    if isinstance(status, int) and status >= 400:
        raise DataSourceError(f"WFS answered HTTP {status} on {typename!r}: {_excerpt(body)}")
    return body


def _excerpt(body: bytes, limit: int = 300) -> str:
    text = body[:8192].decode("utf-8", "replace")
    words = " ".join(re.sub(r"<[^>]*>?", " ", text).split())
    return words[:limit] or "<empty body>"
