"""OpenStreetMap waterways behind the data-source port.

Wraps ``data/variables/hydrography/apis/osm.py``. The third ``features`` source
and the one that shows what the payload kind does **not** promise: Overpass
answers with whatever contributors tagged, so two calls a year apart over one
basin are not the same linework. The port says the shape of the answer, never
its authority.

Like :class:`~hydromodpy.data.source.bdtopage.BdTopageSource` it builds the
Pydantic section its provider function demands, from the one field that
function reads. Rewriting the function to take that field directly is the
better end state and not this phase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import DataRequestError
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

DEFAULT_WATERWAY_TYPES: tuple[str, ...] = ("river", "stream")
"""The default ``HydrographySourceConfig`` declares for this source.

Repeated here rather than imported, so constructing a source pulls in neither
pydantic nor the config kit. ``test_the_declared_defaults_match_the_config``
keeps the two in step.
"""


class OsmSource:
    """OpenStreetMap waterways, served by the Overpass API."""

    source_id: ClassVar[str] = "osm"
    payload_kind: ClassVar[PayloadKind] = "features"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    hosts: ClassVar[tuple[str, ...]] = ("overpass-api.de",)
    writes_out_dir: ClassVar[bool] = False

    def __init__(self, *, waterway_types: tuple[str, ...] = DEFAULT_WATERWAY_TYPES) -> None:
        types = tuple(waterway_types)
        if not types:
            raise DataRequestError(
                "OSM waterway_types is empty, and an Overpass query with no waterway "
                "clause asks for nothing at all."
            )
        for waterway_type in types:
            if not isinstance(waterway_type, str) or not waterway_type.strip():
                raise DataRequestError(f"OSM waterway type {waterway_type!r} is empty.")
        self.waterway_types = types
        self.variables: tuple[str, ...] = ("hydrography",)
        """A river network, whichever waterway tags were asked for."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Download every OSM waterway of the declared types inside the extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)

        from hydromodpy.data.variables.hydrography.apis.osm import fetch as _fetch
        from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

        config = HydrographySourceConfig(
            source="osm",
            waterway_types=list(self.waterway_types),
        )
        frame: gpd.GeoDataFrame = _fetch(config, extent.bbox)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            period=None,
            features=frame,
            metadata={"waterway_types": list(self.waterway_types)},
        )


__all__ = ["DEFAULT_WATERWAY_TYPES", "OsmSource"]
