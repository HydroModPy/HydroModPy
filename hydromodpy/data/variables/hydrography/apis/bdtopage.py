"""Fetch hydrography from the Sandre BD Topage WFS service.

:class:`BdTopageSource` puts the download behind the data-source port, as one
of the three
:class:`~hydromodpy.data.variables.hydrography.apis.features.FeatureSource`.
It asks over a Lambert-93 box and answers in Lambert-93, which is the only
frame the Sandre answers exactly (see
:mod:`hydromodpy.data.common.clients.sandre_topage`).

The default layer is ``TronconHydrographique``: every reach, named or not,
each with ``PersistanceTH``. It used to be ``CoursEau``, the named rivers,
which carries no persistence and leaves out most of the unnamed headwater
network. Over the upper Ille box, ``CoursEau`` held 441 km of the 694 km of
reaches: 253 of the 260 permanent kilometres, 185 of the 434 intermittent ones.

The Sandre vocabulary is mapped to the canonical ``permanence`` column of
:mod:`hydromodpy.data.source.permanence`, next to the native attribute,
which is kept as it came.

``fetch`` serves a caller holding a WGS84 box (site selection); it takes a
``HydrographySourceConfig`` and reads two of its fields, ``typename`` and
``page_size``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar, Final

from hydromodpy.core.exceptions import DataRequestError
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

DEFAULT_TYPENAME = "sa:TronconHydrographique_FXX_Topage2026"
DEFAULT_PAGE_SIZE = 50_000
"""The two defaults ``HydrographySourceConfig`` declares for this source.

Repeated here rather than imported so that constructing a source does not pull
pydantic and the whole config kit into a caller that only wants the vocabulary.
``test_the_declared_defaults_match_the_config`` keeps the two in step.
"""

NAMED_RIVERS_TYPENAME = "sa:CoursEau_FXX_Topage2026"
"""The named rivers, for a caller that wants them rather than every reach.

Site selection snaps a gauging station onto this layer: a station sits on a
named river, and the unnamed headwater reaches would only offer it a wrong
neighbour.
"""

_PERMANENCE_ATTRIBUTES: Final = ("PersistanceTH", "PersistanceSE")
"""The Sandre attributes that say whether water flows all year, by layer.

``PersistanceTH`` on the reaches and ``PersistanceSE`` on the elementary water
surfaces, both filled for every feature. ``CoursEau`` carries none.
"""

_SANDRE_PERMANENCE: Final = {
    "permanent": PERMANENT,
    "intermittent": INTERMITTENT,
    "éphémère": EPHEMERAL,
    "sec": DRY,
    "inconnue": UNKNOWN,
}
"""The five values the Sandre writes, lowercase and accented, to the canonical ones."""


def fetch_projected(
    typename: str,
    bbox: tuple[float, float, float, float],
    *,
    page_size: int,
) -> gpd.GeoDataFrame:
    """Download the features of *typename* touching *bbox*, given in EPSG:2154.

    Returns a GeoDataFrame in EPSG:2154, with a ``permanence`` column when the
    layer carries a persistence attribute.
    """
    frame = sandre_topage.get_features(typename, bbox, page_size=page_size)
    # A milestone: a run that went to a public service for its network says so
    # at the default verbosity, because it is part of where the result comes from.
    logger.info("[WFS] BD Topage %s: fetched %d features", typename, len(frame), extra=MILESTONE)
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
    frame = fetch_projected(
        config.typename,
        box.to_crs(sandre_topage.QUERY_CRS).bbox,
        page_size=config.page_size,
    )
    return frame.to_crs("EPSG:4326")


def with_permanence(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Add the canonical ``permanence`` column read off the Sandre attribute.

    A layer without a persistence attribute is returned unchanged. A value the
    Sandre did not write on 2026-09-27 becomes ``unknown`` and is named in a
    warning, never folded into a known class.
    """
    native = next((name for name in _PERMANENCE_ATTRIBUTES if name in frame.columns), None)
    if native is None:
        return frame
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

    def __init__(
        self,
        *,
        typename: str = DEFAULT_TYPENAME,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        if not isinstance(typename, str) or not typename.strip():
            raise DataRequestError(f"BD Topage typename={typename!r} is empty.")
        sandre_topage.require_metropolitan(typename)
        if not isinstance(page_size, int) or isinstance(page_size, bool) or page_size < 1:
            raise DataRequestError(
                f"BD Topage page_size={page_size!r} is not a positive whole number; "
                "a page of zero features never advances and the paging loop would not end."
            )
        self.typename = typename
        self.page_size = page_size

    def download(self, bbox: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
        return fetch_projected(self.typename, bbox, page_size=self.page_size)

    def metadata(self) -> dict[str, Any]:
        return {"typename": self.typename}


__all__ = [
    "BdTopageSource",
    "DEFAULT_PAGE_SIZE",
    "DEFAULT_TYPENAME",
    "NAMED_RIVERS_TYPENAME",
    "fetch",
    "fetch_projected",
    "with_permanence",
]
