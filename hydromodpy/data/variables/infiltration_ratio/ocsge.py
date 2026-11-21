"""The infiltration ratio from OCS GE of the IGN, one ratio per cover, rasterized at 10 m.

The archives of the departments are the ones the sealed share reads. Each cover
polygon takes the ratio of the longest key of the user's table that starts its
code, and the sealed covers stay nodata, since ``[data.impervious]`` runs them
off whole: a column then averages the ratio over its unsealed ground only. A
cover no key starts is refused with its share of the box, so no cover is given a
value the user did not write.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import DataProductError
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


def ratio_of(code: str, ratios: dict[str, float]) -> float | None:
    """The ratio of cover ``code``: the longest key that starts it, None when no key does."""
    keys = [key for key in ratios if code.startswith(key)]
    return ratios[max(keys, key=len)] if keys else None


def fetch_ocsge_infiltration_ratio(
    *,
    output_dir: Path,
    bbox: tuple[float, float, float, float],
    year: int | None,
    ratios: dict[str, float],
    force_refresh: bool = False,
    bounds: Bounds | None = None,
) -> Path:
    """Write the infiltration ratio of ``bbox`` (EPSG:2154) as a 10 m GeoTIFF, return its path."""
    import pandas as pd

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    table = json.dumps(ratios, sort_keys=True)
    digest = hashlib.sha256(repr((bbox, year, table)).encode()).hexdigest()[:12]
    target = output_dir / f"infiltration_ratio_ocsge_{year or 'latest'}_{digest}.tif"
    if target.exists() and not force_refresh:
        return target
    archives, editions = department_archives(
        output_dir=output_dir, bbox=bbox, year=year, bounds=bounds
    )
    covers = pd.concat([cover_polygons(archive, bbox) for archive in archives])
    covers = covers[~covers["code_cs"].isin(SEALED_COVERS)]
    values = covers["code_cs"].map(lambda code: ratio_of(str(code), ratios))
    missing = covers[values.isna()]
    if not missing.empty:
        share = missing.geometry.area.groupby(missing["code_cs"]).sum() / covers.geometry.area.sum()
        listed = ", ".join(f"{code} ({100 * s:.1f} %)" for code, s in share.sort_values().items())
        raise DataProductError(
            f"[data.infiltration_ratio] ratios gives no value to the OCS GE covers {listed} "
            'of the area: add a key for each, or "CS" for every cover left.'
        )
    return burn_map(
        target,
        bbox,
        zip(covers.geometry, values.astype(float), strict=True),
        fill=-1.0,
        editions=editions,
    )


class OcsgeInfiltrationRatio:
    """OCS GE of the IGN as a source of the infiltration ratio, 10 m, France."""

    section: ClassVar[str] = "infiltration_ratio"
    source_id: ClassVar[str] = "ocsge"
    payload_kind: ClassVar[PayloadKind] = "files"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    writes_out_dir: ClassVar[bool] = True

    def __init__(
        self,
        *,
        year: int | None = None,
        ratios: dict[str, float] | None = None,
        force_refresh: bool = False,
    ) -> None:
        # The section writes both; a source built without them reads a bare "CS" table.
        self.year = None if year is None else int(year)
        self.ratios = dict(ratios) if ratios else {"CS": 1.0}
        self.force_refresh = bool(force_refresh)
        self.variables = ("infiltration_ratio",)
        self.hosts = shipped_hosts(self.source_id)

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Build the infiltration ratio over the request's extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)
        path = fetch_ocsge_infiltration_ratio(
            output_dir=request.out_dir,
            bbox=extent.bbox,
            year=self.year,
            ratios=self.ratios,
            force_refresh=self.force_refresh,
            bounds=getattr(request, "bounds", None),
        )
        from hydromodpy.data.contracts.file_record import FileRecord

        record = FileRecord.of(path, state="conditioned", nodata=-1.0, origin=OCSGE_ORIGIN)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            files=(record,),
            metadata={"year": self.year, "ratios": self.ratios},
        )


__all__ = ["OcsgeInfiltrationRatio", "fetch_ocsge_infiltration_ratio", "ratio_of"]
