"""Hub'Eau piezometry behind the data-source port.

Wraps ``data/variables/piezometry/apis/hubeau.py`` without changing it. What
the port adds over calling that function directly is the whole point of the
phase: the extent arrives in whatever CRS the caller had and reaches Hub'Eau in
WGS84, the period is a checked pair instead of two loose datetimes, and the two
selectors -- a box or a list of station codes -- are declared rather than
discovered by reading the first ``if`` of the function body.

Everything that belongs to *this* Hub'Eau endpoint and to no other source --
which product, whether a piezometer with no observation in the window is kept,
how far to widen the search when the box holds none -- is fixed when the source
is built. The request carries only what changes between two questions put to
the same source.
"""

from __future__ import annotations

from typing import ClassVar

from hydromodpy.core.exceptions import DataRequestError
from hydromodpy.data.source.port import (
    Extent,
    FetchRequest,
    FetchResult,
    PayloadKind,
    PeriodNeed,
    Selector,
    extent_for,
    require_declared_variables,
    require_period,
    require_selectors,
)

PRODUCT_VARIABLE: dict[str, str] = {
    "level": "groundwater_level",
    "depth": "groundwater_depth",
}
"""What the Hub'Eau product selects, and what the records it returns are named.

Read off the adapter rather than invented: ``piezometry/apis/hubeau.py`` sets
``variable="groundwater_level"`` for ``product="level"`` and
``"groundwater_depth"`` for ``"depth"``. The table lives here so the port can
compare the declaration against what comes back.
"""


class HubeauPiezometrySource:
    """Groundwater levels from the Hub'Eau ``niveaux_nappes`` endpoints."""

    source_id: ClassVar[str] = "hubeau-piezometry"
    payload_kind: ClassVar[PayloadKind] = "points"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent", "station_ids")
    period_need: ClassVar[PeriodNeed] = "required"
    hosts: ClassVar[tuple[str, ...]] = ("hubeau.eaufrance.fr",)
    writes_out_dir: ClassVar[bool] = False

    def __init__(
        self,
        *,
        product: str = "level",
        require_observations: bool = True,
        fallback_search_radius_km: float | None = None,
        nearest_to: tuple[float, float] | None = None,
    ) -> None:
        if product not in PRODUCT_VARIABLE:
            raise DataRequestError(
                f"Unknown Hub'Eau piezometry product {product!r}. "
                f"Expected one of {sorted(PRODUCT_VARIABLE)}."
            )
        if nearest_to is not None:
            try:
                lon, lat = nearest_to
            except (TypeError, ValueError) as exc:
                raise DataRequestError(
                    f"nearest_to={nearest_to!r} is not a (lon, lat) pair."
                ) from exc
            nearest_to = (float(lon), float(lat))
        self.product = product
        self.variables: tuple[str, ...] = (PRODUCT_VARIABLE[product],)
        """The one variable this instance emits, of the two the class can serve."""
        self.require_observations = bool(require_observations)
        self.fallback_search_radius_km = fallback_search_radius_km
        self.nearest_to = nearest_to

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Fetch the configured product over the request's extent or stations."""
        require_selectors(self, request)
        period = require_period(self, request)
        assert period is not None  # period_need == "required", checked just above
        extent: Extent | None = None
        if request.extent is not None:
            extent = extent_for(self, request)

        from hydromodpy.data.variables.piezometry.apis.hubeau import fetch as _fetch

        records = _fetch(
            product=self.product,
            bbox=extent.bbox if extent is not None else None,
            station_ids=list(request.station_ids) or None,
            date_start=period.start,
            date_end=period.end,
            nearest_to=self.nearest_to,
            require_observations=self.require_observations,
            fallback_search_radius_km=self.fallback_search_radius_km,
        )
        require_declared_variables(self, [record.variable for record in records])
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            period=period,
            points=tuple(records),
            metadata={"product": self.product},
        )


__all__ = ["PRODUCT_VARIABLE", "HubeauPiezometrySource"]
