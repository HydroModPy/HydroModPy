"""Fetch hydrography from the Sandre BD Topage WFS service.

``fetch`` serves the hydrography manager. :class:`BdTopageSource` puts the
same function behind the data-source port. It is there beside a
Hub'Eau source, and not because it is the easiest second one: it is the one
that disagrees with Hub'Eau on every question the port asks. It returns a
feature table rather than records, it has no time axis at all, and it cannot be
asked for a station. A conformance suite that only held two point sources would
prove nothing about the port.

The Sandre WFS is queried in WGS84, which it shares with Hub'Eau. The pair that
proves the reprojection is this source against the IGN one, both of which the
suite runs with a caller extent in Lambert-93.

Why this adapter builds a Pydantic config it was not given
----------------------------------------------------------
``bdtopage.fetch`` takes a ``HydrographySourceConfig`` and reads exactly two of
its nine fields, ``typename`` and ``page_size``. The port does not pass config
objects, so the adapter takes those two values and builds what the function
demands. Rewriting the function to take them directly would be the better end
state and it is not this phase: the api layer keeps its callers until the
capability that replaces them exists.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.core.io.http_client import get_default_client
from hydromodpy.core.logging import get_logger
from hydromodpy.core.progress import MILESTONE
from hydromodpy.data.source.port import (
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    extent_for,
    require_period,
    require_selectors,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

    from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

logger = get_logger(__name__)

WFS_URL = "https://services.sandre.eaufrance.fr/geo/sandre"
OUT_GEOJSON = "application/json; subtype=geojson"


def _bbox_crs84(bbox_wgs84: tuple[float, float, float, float]) -> str:
    """Format *bbox_wgs84* for WFS 2.0 CRS84 axis order (lon, lat)."""
    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    return f"{lon_min},{lat_min},{lon_max},{lat_max},urn:ogc:def:crs:OGC:1.3:CRS84"


def _wfs_hits(typename: str, bbox_wgs84: tuple[float, float, float, float]) -> int:
    """Fast count of features in *bbox_wgs84* (resultType=hits)."""
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": typename,
        "resulttype": "hits",
        "bbox": _bbox_crs84(bbox_wgs84),
    }
    r = get_default_client().get(WFS_URL, params=params, timeout=120)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    return int(root.attrib.get("numberMatched", "0"))


def fetch(
    config: HydrographySourceConfig,
    bbox_wgs84: tuple[float, float, float, float],
) -> gpd.GeoDataFrame:
    """Download BD Topage features inside *bbox_wgs84*.

    Returns a GeoDataFrame in EPSG:4326.
    """
    import geopandas as gpd

    typename = config.typename
    page_size = config.page_size

    n = _wfs_hits(typename, bbox_wgs84)
    logger.info("[WFS] BD Topage matched features in bbox: %d", n)
    if n == 0:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    features: list = []
    start = 0

    while True:
        params = {
            "service": "WFS",
            "version": "2.0.0",
            "request": "GetFeature",
            "typeNames": typename,
            "outputFormat": OUT_GEOJSON,
            "bbox": _bbox_crs84(bbox_wgs84),
            "count": page_size,
            "startIndex": start,
        }
        r = get_default_client().get(WFS_URL, params=params, timeout=120)
        r.raise_for_status()

        data = r.json()
        page = data.get("features", [])
        features.extend(page)

        logger.debug("[WFS] page startIndex=%d: %d features", start, len(page))

        if len(page) < page_size:
            break
        start += page_size

    # A milestone: a run that went to a public service for its network says so
    # at the default verbosity, because it is part of where the result comes from.
    logger.info("[WFS] BD Topage: fetched %d features total", len(features), extra=MILESTONE)
    return gpd.GeoDataFrame.from_features(features, crs="EPSG:4326")


DEFAULT_TYPENAME = "sa:CoursEau_FXX_Topage2025"
DEFAULT_PAGE_SIZE = 2000
"""The two defaults ``HydrographySourceConfig`` declares for this source.

Repeated here rather than imported so that constructing a source does not pull
pydantic and the whole config kit into a caller that only wants the vocabulary.
``test_the_declared_defaults_match_the_config`` keeps the two in step.
"""


class BdTopageSource:
    """The French BD Topage river network, served by the Sandre WFS."""

    source_id: ClassVar[str] = "bdtopage"
    payload_kind: ClassVar[PayloadKind] = "features"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    hosts: ClassVar[tuple[str, ...]] = ("services.sandre.eaufrance.fr",)
    writes_out_dir: ClassVar[bool] = False

    def __init__(
        self,
        *,
        typename: str = DEFAULT_TYPENAME,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        if not isinstance(typename, str) or not typename.strip():
            raise DataRequestError(f"BD Topage typename={typename!r} is empty.")
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            raise DataRequestError(
                f"BD Topage page_size={page_size!r} is not a positive whole number; "
                "a page of zero features never advances and the paging loop would not end."
            )
        self.typename = typename
        self.page_size = page_size
        self.variables: tuple[str, ...] = ("hydrography",)
        """A reference river network, whatever the typename selects."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Download every BD Topage feature inside the request's extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)

        from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

        config = HydrographySourceConfig(
            source="bdtopage",
            typename=self.typename,
            page_size=self.page_size,
        )
        frame: gpd.GeoDataFrame = fetch(config, extent.bbox)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            period=None,
            features=frame,
            metadata={"typename": self.typename},
        )


__all__ = [
    "BdTopageSource",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_TYPENAME",
    "fetch",
]
