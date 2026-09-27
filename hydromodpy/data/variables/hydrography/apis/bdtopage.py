"""Fetch hydrography from the Sandre BD Topage WFS service.

:class:`BdTopageSource` puts the download behind the data-source port, as one
of the three
:class:`~hydromodpy.data.variables.hydrography.apis.features.FeatureSource`.
It asks over a Lambert-93 box and answers in Lambert-93, which is the only
frame the Sandre answers exactly (see
:mod:`hydromodpy.data.common.clients.sandre_topage`).

It reads one layer, ``TronconHydrographique``: every reach, named or not,
each with ``PersistanceTH``. That is the hydrographic extent; its permanent
reaches are the network that still flows at low water. The Sandre vocabulary
is mapped to the canonical ``permanence`` column of
:mod:`hydromodpy.data.source.permanence`, next to the native attribute, which
is kept as it came.

``fetch`` serves a caller holding a WGS84 box (site selection); it takes a
``HydrographySourceConfig`` and reads its ``page_size``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Final

from hydromodpy.core.exceptions import DataRequestError, DataSourceError
from hydromodpy.core.logging import get_logger
from hydromodpy.core.progress import MILESTONE
from hydromodpy.data.common.clients import sandre_topage
from hydromodpy.data.source.permanence import (
    DRY,
    EPHEMERAL,
    INTERMITTENT,
    PERMANENCE_COLUMN,
    PERMANENT,
    UNKNOWN,
)
from hydromodpy.data.variables.hydrography.apis.features import FeatureSource

if TYPE_CHECKING:  # pragma: no cover - typing only
    import geopandas as gpd

    from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

logger = get_logger(__name__)

WFS_URL = sandre_topage.SANDRE_WFS_URL

LAYER: Final = "sa:TronconHydrographique_FXX_Topage2026"
"""The reaches of metropolitan France, 2026 vintage. A new vintage changes this line."""

DEFAULT_PAGE_SIZE = 50_000
"""The default ``HydrographySourceConfig`` declares for this source.

Repeated here rather than imported so that constructing a source does not pull
pydantic and the whole config kit into a caller that only wants the vocabulary.
``test_the_bdtopage_defaults_match_the_config_they_replace`` keeps the two in step.
"""

_PERMANENCE_ATTRIBUTE: Final = "PersistanceTH"

_SANDRE_PERMANENCE: Final = {
    "permanent": PERMANENT,
    "intermittent": INTERMITTENT,
    "éphémère": EPHEMERAL,
    "sec": DRY,
    "inconnue": UNKNOWN,
}
"""The five values the Sandre writes, lowercase and accented, to the canonical ones."""


def fetch_projected(
    bbox: tuple[float, float, float, float],
    *,
    page_size: int,
) -> gpd.GeoDataFrame:
    """Download every reach touching *bbox*, given in EPSG:2154, with its permanence.

    Returns a GeoDataFrame in EPSG:2154.
    """
    frame = sandre_topage.get_features(LAYER, bbox, page_size=page_size)
    # A milestone: a run that went to a public service for its network says so
    # at the default verbosity, because it is part of where the result comes from.
    logger.info("[WFS] BD Topage %s: fetched %d reaches", LAYER, len(frame), extra=MILESTONE)
    return with_permanence(frame)


def fetch(
    config: HydrographySourceConfig,
    bbox_wgs84: tuple[float, float, float, float],
) -> gpd.GeoDataFrame:
    """Download BD Topage features inside *bbox_wgs84*, in EPSG:4326.

    For a caller holding degrees. The box is converted to the Lambert-93 box
    that contains it, which asks for slightly more than *bbox_wgs84*; cut the
    answer to a shape if that matters.
    """
    from hydromodpy.data.source.port import Extent

    lon_min, lat_min, lon_max, lat_max = bbox_wgs84
    box = Extent(xmin=lon_min, ymin=lat_min, xmax=lon_max, ymax=lat_max, crs="EPSG:4326")
    frame = fetch_projected(box.to_crs(sandre_topage.QUERY_CRS).bbox, page_size=config.page_size)
    return frame.to_crs("EPSG:4326")


def with_permanence(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add the canonical ``permanence`` column read off ``PersistanceTH``.

    A value the Sandre did not write on 2026-09-27 becomes ``unknown`` and is
    named in a warning, never folded into a known class. Reaches arriving
    without the attribute mean the layer changed under this build, and raise.
    """
    native = _PERMANENCE_ATTRIBUTE
    if frame.empty:
        return frame
    if native not in frame.columns:
        raise DataSourceError(
            f"BD Topage {LAYER} answered reaches without {native}: the layer changed, and "
            "which reaches are permanent can no longer be read."
        )
    values = frame[native]
    mapped = values.map(
        lambda value: (
            _SANDRE_PERMANENCE.get(value.strip().lower()) if isinstance(value, str) else None
        )
    )
    unmapped = sorted({str(value) for value in values[mapped.isna() & values.notna()]})
    if unmapped:
        logger.warning(
            "BD Topage %s holds values this build does not know, read as 'unknown': %s",
            native,
            ", ".join(unmapped),
        )
    frame[PERMANENCE_COLUMN] = mapped.fillna(UNKNOWN).astype(object)
    return frame


class BdTopageSource(FeatureSource):
    """The French BD Topage river network, served by the Sandre WFS."""

    source_id: ClassVar[str] = "bdtopage"
    hosts: ClassVar[tuple[str, ...]] = (sandre_topage.SANDRE_WFS_HOST,)
    extent_crs: ClassVar[str] = sandre_topage.QUERY_CRS

    def __init__(self, *, page_size: int = DEFAULT_PAGE_SIZE) -> None:
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            raise DataRequestError(
                f"BD Topage page_size={page_size!r} is not a positive whole number; "
                "a page of zero features never advances and the paging loop would not end."
            )
        self.page_size = page_size

    def download(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        return fetch_projected(bbox, page_size=self.page_size)

    def metadata(self) -> dict[str, Any]:
        return {"typename": LAYER}


__all__ = [
    "BdTopageSource",
    "DEFAULT_PAGE_SIZE",
    "LAYER",
    "fetch",
    "fetch_projected",
    "with_permanence",
]
