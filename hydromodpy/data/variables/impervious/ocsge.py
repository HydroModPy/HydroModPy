"""The sealed share from OCS GE of the IGN, rasterized at 10 m over the request.

OCS GE 2.0 is served as one 7z archive per department and edition, about 200 MB
for Ille-et-Vilaine, by the download service of the Geoplateforme. The archive
stays in the cache, and each request extracts the layer ``OCCUPATION_SOL``,
keeps the polygons of the two sealed covers and burns them on a 10 m grid: 1 on
a sealed pixel, 0 elsewhere. On the Nancon (2023), the catchment is 3.95 %
sealed, 1.56 % built and 2.39 % roads and car parks.
"""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from filelock import FileLock

from hydromodpy.core.exceptions import DataProductError
from hydromodpy.core.io.atomic_replace import staged_path
from hydromodpy.core.io.fetch import HTTPClient, download, open_client
from hydromodpy.core.logging import get_logger
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

logger = get_logger(__name__)

OCSGE_ORIGIN = "https://data.geopf.fr/telechargement/resource/OCSGE"
"""The service ``fetch`` answers of, for the :class:`FileRecord` it returns."""

SEALED_COVERS: tuple[str, ...] = ("CS1.1.1.1", "CS1.1.1.2")
"""OCS GE covers read as sealed: built areas, and unbuilt sealed areas (roads, car parks).

Mineral surfaces (CS1.1.2.1, gravel and quarries) let water through and are left out.
"""

PIXEL_M = 10.0


def _editions(code: str, client: HTTPClient) -> dict[int, str]:
    """The OCS GE 2.0 editions of department ``code``, year to package name."""
    text = client.get(f"{OCSGE_ORIGIN}?zone=D{code}").text
    pattern = re.compile(rf"<title>(OCS-GE_2-0__GPKG_LAMB93_D{code}_(\d{{4}})-\d\d-\d\d)</title>")
    return {int(year): name for name, year in pattern.findall(text)}


def _edition(code: str, year: int | None, client: HTTPClient) -> str:
    """The package of the latest edition of ``code`` not after ``year``, or the latest."""
    editions = _editions(code, client)
    held = [y for y in editions if year is None or y <= year]
    if not held:
        listed = sorted(editions) or "none"
        raise DataProductError(
            f"OCS GE 2.0 has no edition of department {code} up to {year}, and the IGN "
            f"serves {listed}: write a later year under [data.impervious], or give the "
            'sealed share as a file with source = "file".'
        )
    return editions[max(held)]


def _sealed_polygons(archive: Path, bbox: tuple[float, float, float, float]):
    """The sealed polygons of the archive inside ``bbox``, EPSG:2154."""
    import geopandas as gpd
    import py7zr

    with py7zr.SevenZipFile(archive) as packed:
        targets = [n for n in packed.getnames() if n.endswith("/OCCUPATION_SOL.gpkg")]
        if not targets:
            raise DataProductError(f"{archive.name} holds no OCCUPATION_SOL layer.")
        with tempfile.TemporaryDirectory(dir=archive.parent) as scratch:
            packed.extract(path=scratch, targets=targets)
            covers = ", ".join(f"'{code}'" for code in SEALED_COVERS)
            frame = gpd.read_file(
                Path(scratch) / targets[0],
                bbox=bbox,
                where=f"code_cs IN ({covers})",
                columns=["code_cs"],
            )
    return frame.to_crs("EPSG:2154") if frame.crs is not None else frame.set_crs("EPSG:2154")


def fetch_ocsge_impervious(
    *,
    output_dir: Path,
    bbox: tuple[float, float, float, float],
    year: int | None,
    force_refresh: bool = False,
    bounds: Bounds | None = None,
) -> Path:
    """Write the sealed share of ``bbox`` (EPSG:2154) as a 10 m GeoTIFF, and return its path."""
    import numpy as np
    import pandas as pd
    import rasterio
    from rasterio.features import rasterize
    from rasterio.transform import from_origin

    from hydromodpy.catchment.administrative.france import find_departments_in_bbox

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(repr((bbox, year)).encode()).hexdigest()[:12]
    target = output_dir / f"impervious_ocsge_{year or 'latest'}_{digest}.tif"
    if target.exists() and not force_refresh:
        return target

    codes = find_departments_in_bbox(bbox)
    if not codes:
        raise DataProductError(
            f"No French department meets the box {bbox} (EPSG:2154): OCS GE covers France "
            'only. Use source = "worldcover" elsewhere.'
        )
    archives = output_dir / "ocsge_departments"
    archives.mkdir(exist_ok=True)
    frames = []
    editions = []
    with open_client(bounds=bounds) as http:
        for code in codes:
            name = _edition(code, year, http)
            editions.append(name)
            archive = archives / f"{name}.7z"
            with FileLock(f"{archive}.lock"):
                if not archive.exists():
                    logger.info("[impervious] downloading %s", name)
                    download(
                        f"https://data.geopf.fr/telechargement/download/OCSGE/{name}/{name}.7z",
                        archive,
                        bounds=bounds,
                        client=http,
                    )
                frames.append(_sealed_polygons(archive, bbox))

    xmin = np.floor(bbox[0] / PIXEL_M) * PIXEL_M
    ymax = np.ceil(bbox[3] / PIXEL_M) * PIXEL_M
    width = int(np.ceil((bbox[2] - xmin) / PIXEL_M))
    height = int(np.ceil((ymax - bbox[1]) / PIXEL_M))
    transform = from_origin(xmin, ymax, PIXEL_M, PIXEL_M)
    sealed = pd.concat(frames, ignore_index=True)
    grid = np.zeros((height, width), dtype="float32")
    if not sealed.empty:
        grid = rasterize(
            ((geometry, 1.0) for geometry in sealed.geometry),
            out_shape=(height, width),
            transform=transform,
            fill=0.0,
            dtype="float32",
        )
    with staged_path(target) as staged:
        with rasterio.open(
            staged,
            "w",
            driver="GTiff",
            width=width,
            height=height,
            count=1,
            dtype="float32",
            crs="EPSG:2154",
            transform=transform,
            nodata=-1.0,
            compress="deflate",
        ) as out:
            out.write(grid, 1)
            # The editions read, one per department, stay with the map.
            out.update_tags(ocsge_editions=" ".join(editions))
    return target


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


__all__ = ["SEALED_COVERS", "OcsgeImpervious", "fetch_ocsge_impervious"]
