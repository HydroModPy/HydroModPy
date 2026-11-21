"""The sealed share from ESA WorldCover, its built-up class at 10 m, over the world.

WorldCover is served as cloud-optimised GeoTIFF tiles of 3 by 3 degrees on a
public bucket, so a request reads only the window of its box, in a few seconds.
Class 50, built-up, is read as sealed (1) and every other class as open (0).
At 10 m a narrow road falls in the field beside it: on the Nancon, WorldCover
gives 2.4 % built-up where OCS GE gives 3.95 % sealed.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from hydromodpy.core.exceptions import DataProductError, NetworkError
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.io.fetch import open_client, vsicurl_path
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

WORLDCOVER_ORIGIN = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
"""The bucket ``fetch`` answers of, for the :class:`FileRecord` it returns."""

BUILT_UP_CLASS = 50
VERSIONS: dict[int, str] = {2020: "v100", 2021: "v200"}
TILE_DEGREES = 3


def tile_names(bbox: tuple[float, float, float, float]) -> list[str]:
    """Names of the tiles that meet ``bbox`` (lon/lat), such as ``N48W003``."""
    names = []
    lat_start = math.floor(bbox[1] / TILE_DEGREES) * TILE_DEGREES
    lon_start = math.floor(bbox[0] / TILE_DEGREES) * TILE_DEGREES
    for lat in range(lat_start, math.ceil(bbox[3] / TILE_DEGREES) * TILE_DEGREES, TILE_DEGREES):
        for lon in range(lon_start, math.ceil(bbox[2] / TILE_DEGREES) * TILE_DEGREES, TILE_DEGREES):
            ns = "N" if lat >= 0 else "S"
            ew = "E" if lon >= 0 else "W"
            names.append(f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}")
    return names


def tile_url(name: str, year: int) -> str:
    """URL of one WorldCover map tile."""
    version = VERSIONS[year]
    return f"{WORLDCOVER_ORIGIN}/{version}/{year}/map/ESA_WorldCover_10m_{year}_{version}_{name}_Map.tif"


def fetch_worldcover_impervious(
    *,
    output_dir: Path,
    bbox: tuple[float, float, float, float],
    year: int,
    force_refresh: bool = False,
    bounds: Bounds | None = None,
) -> Path:
    """Write the sealed share of ``bbox`` (EPSG:4326) as a 10 m GeoTIFF, and return its path."""
    import numpy as np
    import rasterio
    from rasterio.merge import merge

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(repr((bbox, year)).encode()).hexdigest()[:12]
    target = output_dir / f"impervious_worldcover_{year}_{digest}.tif"
    if target.exists() and not force_refresh:
        return target

    paths = []
    with open_client(bounds=bounds) as http:
        for name in tile_names(bbox):
            try:
                paths.append(vsicurl_path(tile_url(name, year), bounds=bounds, client=http))
            except NetworkError as exc:
                # The bucket has no tile over open sea.
                if "404" not in str(exc):
                    raise
    if not paths:
        raise DataProductError(f"WorldCover {year} has no tile over the box {bbox}.")
    datasets = [rasterio.open(path) for path in paths]
    try:
        classes, transform = merge(datasets, bounds=bbox, nodata=0)
    finally:
        for dataset in datasets:
            dataset.close()
    classes = classes[0]
    sealed = np.where(classes == 0, -1.0, (classes == BUILT_UP_CLASS).astype("float32"))
    with staged_path(target) as staged:
        with rasterio.open(
            staged,
            "w",
            driver="GTiff",
            width=sealed.shape[1],
            height=sealed.shape[0],
            count=1,
            dtype="float32",
            crs="EPSG:4326",
            transform=transform,
            nodata=-1.0,
            compress="deflate",
        ) as out:
            out.write(sealed.astype("float32"), 1)
    return target


class WorldcoverImpervious:
    """ESA WorldCover as a source of the sealed share, 10 m, the world."""

    section: ClassVar[str] = "impervious"
    source_id: ClassVar[str] = "worldcover"
    payload_kind: ClassVar[PayloadKind] = "files"
    extent_crs: ClassVar[str] = "EPSG:4326"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    writes_out_dir: ClassVar[bool] = True

    def __init__(self, *, year: int = 2021, force_refresh: bool = False) -> None:
        if year not in VERSIONS:
            raise DataProductError(f"WorldCover has maps for {sorted(VERSIONS)}, not {year}.")
        self.year = int(year)
        self.force_refresh = bool(force_refresh)
        self.variables = ("impervious",)
        self.hosts = shipped_hosts(self.source_id)

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Read the built-up class over the request's extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)
        path = fetch_worldcover_impervious(
            output_dir=request.out_dir,
            bbox=extent.bbox,
            year=self.year,
            force_refresh=self.force_refresh,
            bounds=getattr(request, "bounds", None),
        )
        from hydromodpy.data.contracts.file_record import FileRecord

        record = FileRecord.of(path, state="conditioned", nodata=-1.0, origin=WORLDCOVER_ORIGIN)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            files=(record,),
            metadata={"year": self.year, "built_up_class": BUILT_UP_CLASS},
        )


__all__ = ["WorldcoverImpervious", "fetch_worldcover_impervious", "tile_names", "tile_url"]
