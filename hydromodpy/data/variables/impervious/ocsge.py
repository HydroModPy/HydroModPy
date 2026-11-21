"""The sealed share from OCS GE of the IGN, rasterized at 10 m over the request.

The archives and the grid are read by ``data/common/clients/ocsge.py``. Each
request keeps the polygons of the two sealed covers and burns them on a 10 m
grid: 1 on a sealed pixel, 0 elsewhere. On the Nancon (2023), the catchment is 3.95 %
sealed, 1.56 % built and 2.39 % roads and car parks.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.data.common.clients.ocsge import (
    OCSGE_ORIGIN,
    SEALED_COVERS,
    burn_map,
    cover_polygons,
    department_archives,
)
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
    from hydromodpy.core.runtime.bounds import Bounds


def fetch_ocsge_impervious(
    *,
    output_dir: Path,
    bbox: tuple[float, float, float, float],
    year: int | None,
    force_refresh: bool = False,
    bounds: Bounds | None = None,
) -> Path:
    """Write the sealed share of ``bbox`` (EPSG:2154) as a 10 m GeoTIFF, and return its path."""
    import pandas as pd

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(repr((bbox, year)).encode()).hexdigest()[:12]
    target = output_dir / f"impervious_ocsge_{year or 'latest'}_{digest}.tif"
    if target.exists() and not force_refresh:
        return target
    archives, editions = department_archives(bbox=bbox, year=year, bounds=bounds)
    sealed = pd.concat([cover_polygons(a, bbox, SEALED_COVERS) for a in archives])
    return burn_map(target, bbox, ((g, 1.0) for g in sealed.geometry), fill=0.0, editions=editions)


class OcsgeImpervious:
    """OCS GE of the IGN as a source of the sealed share, 10 m, France."""

    section: ClassVar[str] = "impervious"
    source_id: ClassVar[str] = "ocsge"
    payload_kind: ClassVar[PayloadKind] = "files"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    writes_out_dir: ClassVar[bool] = True

    def __init__(self, *, year: int | None = None, force_refresh: bool = False) -> None:
        # None reads the latest edition, which a new edition moves; the section writes a year.
        self.year = None if year is None else int(year)
        self.force_refresh = bool(force_refresh)
        self.variables = ("impervious",)
        self.hosts = shipped_hosts(self.source_id)

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Build the sealed share over the request's extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)
        bounds = getattr(request, "bounds", None)
        path = fetch_ocsge_impervious(
            output_dir=request.out_dir,
            bbox=extent.bbox,
            year=self.year,
            force_refresh=self.force_refresh,
            bounds=bounds,
        )
        from hydromodpy.data.contracts.file_record import FileRecord

        record = FileRecord.of(path, state="conditioned", nodata=-1.0, origin=OCSGE_ORIGIN)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            files=(record,),
            metadata={"year": self.year, "sealed_covers": list(SEALED_COVERS)},
        )


__all__ = ["OcsgeImpervious", "fetch_ocsge_impervious"]
