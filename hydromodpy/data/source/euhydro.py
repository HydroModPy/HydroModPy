"""The EU-Hydro river network behind the data-source port.

Wraps ``data/variables/hydrography/apis/euhydro.py``. Continental where the
other two ``features`` sources are national, and the one whose request is not a
single call: the adapter's provider function discovers the feature layers of a
MapServer group, then pages each of them. The port sees one question and one
answer, which is what lets a caller ask the three the same way.

``euhydro_page_size`` carries its provider's name because the flat
``[[data.hydrography.sources]]`` section already spent ``page_size`` on BD
Topage, and the generic binder hands a source the section field its constructor
names. The prefix belongs to the section, not to this class, and it goes when
the section becomes a tagged union.
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

DEFAULT_GROUP_NAME = "River_Net_lines"
DEFAULT_PAGE_SIZE = 1000
"""The two defaults ``HydrographySourceConfig`` declares for this source.

Repeated here rather than imported, for the reason BD Topage gives: the
vocabulary stays importable without pydantic.
``test_the_declared_defaults_match_the_config`` keeps the two in step.
"""


class EuHydroSource:
    """The EEA EU-Hydro river network, served by the Discomap MapServer."""

    source_id: ClassVar[str] = "euhydro"
    payload_kind: ClassVar[PayloadKind] = "features"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    hosts: ClassVar[tuple[str, ...]] = ("image.discomap.eea.europa.eu",)
    writes_out_dir: ClassVar[bool] = False

    def __init__(
        self,
        *,
        group_name: str = DEFAULT_GROUP_NAME,
        euhydro_page_size: int = DEFAULT_PAGE_SIZE,
    ) -> None:
        if not isinstance(group_name, str) or not group_name.strip():
            raise DataRequestError(f"EU-Hydro group_name={group_name!r} is empty.")
        if (
            not isinstance(euhydro_page_size, int)
            or isinstance(euhydro_page_size, bool)
            or euhydro_page_size < 1
        ):
            raise DataRequestError(
                f"EU-Hydro euhydro_page_size={euhydro_page_size!r} is not a positive whole "
                "number; a page of zero features never advances and the paging loop would "
                "not end."
            )
        self.group_name = group_name
        self.euhydro_page_size = euhydro_page_size
        self.variables: tuple[str, ...] = ("hydrography",)
        """A river network, whichever layers the group holds."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Download every EU-Hydro feature of the group inside the extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)

        from hydromodpy.data.variables.hydrography.apis.euhydro import fetch as _fetch
        from hydromodpy.data.variables.hydrography.config import HydrographySourceConfig

        config = HydrographySourceConfig(
            source="euhydro",
            group_name=self.group_name,
            euhydro_page_size=self.euhydro_page_size,
        )
        frame: gpd.GeoDataFrame = _fetch(config, extent.bbox)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            period=None,
            features=frame,
            metadata={"group_name": self.group_name},
        )


__all__ = ["DEFAULT_GROUP_NAME", "DEFAULT_PAGE_SIZE", "EuHydroSource"]
