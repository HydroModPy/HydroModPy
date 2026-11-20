"""What the three river-network sources share behind the data-source port.

BD Topage, EU-Hydro and OpenStreetMap answer the same question the same way: a
feature table over a box in WGS84, with no time axis and nothing written under
the request's directory. A subclass names its source, validates its own options,
and says how to download a box; the section is the one they all serve, and the
hosts are read from the licence table on the pattern every shipped source
follows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from hydromodpy.core.io.fetch import open_client
from hydromodpy.data.source.port import (
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    extent_for,
    require_period,
    require_selectors,
    shipped_hosts,
)

if TYPE_CHECKING:
    import geopandas as gpd

    from hydromodpy.core.io.fetch import HTTPClient

NETWORK_VARIABLES: tuple[str, ...] = ("hydrography",)


class FeatureSource:
    """A river network over a WGS84 box, with no time axis."""

    source_id: ClassVar[str]
    section: ClassVar[str] = "hydrography"
    payload_kind: ClassVar[PayloadKind] = "features"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    writes_out_dir: ClassVar[bool] = False
    variables: tuple[str, ...] = NETWORK_VARIABLES

    @property
    def hosts(self) -> tuple[str, ...]:
        """The hosts of this network, read from the licence table this build ships."""
        return shipped_hosts(self.source_id)

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Download every feature inside the request's extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)
        with open_client(request.bounds) as client:
            features = self.download(extent.bbox, client=client)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            period=None,
            features=features,
            metadata=self.metadata(),
        )

    def download(
        self, bbox: tuple[float, float, float, float], *, client: HTTPClient
    ) -> gpd.GeoDataFrame:
        """The features inside ``bbox``, in WGS84, read through the call's client."""
        raise NotImplementedError

    def metadata(self) -> dict[str, Any]:
        """The options a result reports about the question it answered."""
        return {}


__all__ = ["NETWORK_VARIABLES", "FeatureSource"]
