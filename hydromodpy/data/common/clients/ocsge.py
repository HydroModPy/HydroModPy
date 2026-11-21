"""OCS GE of the IGN: the department archives, their cover polygons, and a 10 m grid to burn.

OCS GE 2.0 is served as one 7z archive per department and edition, about 200 MB
for Ille-et-Vilaine, by the download service of the Geoplateforme. The archive
stays in the cache, and each request extracts the layer ``OCCUPATION_SOL``. The
sealed share and the infiltration ratio both read it. The network and raster
libraries are imported inside the functions, so a configuration that names the
covers loads none of them.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from hydromodpy.core.exceptions import DataProductError
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    from hydromodpy.core.io.fetch import HTTPClient
    from hydromodpy.core.runtime.bounds import Bounds

logger = get_logger(__name__)

OCSGE_ORIGIN = "https://data.geopf.fr/telechargement/resource/OCSGE"
"""The service the archives come from, for the :class:`FileRecord` a source returns."""

SEALED_COVERS: tuple[str, ...] = ("CS1.1.1.1", "CS1.1.1.2")
"""OCS GE covers read as sealed: built areas, and unbuilt sealed areas (roads, car parks).

Mineral surfaces (CS1.1.2.1, gravel and quarries) let water through and are left out.
"""

PIXEL_M = 10.0


def editions(code: str, client: HTTPClient) -> dict[int, str]:
    """The OCS GE 2.0 editions of department ``code``, year to package name."""
    text = client.get(f"{OCSGE_ORIGIN}?zone=D{code}").text
    pattern = re.compile(rf"<title>(OCS-GE_2-0__GPKG_LAMB93_D{code}_(\d{{4}})-\d\d-\d\d)</title>")
    return {int(year): name for name, year in pattern.findall(text)}


def edition(code: str, year: int | None, client: HTTPClient) -> str:
    """The package of the latest edition of ``code`` not after ``year``, or the latest."""
    served = editions(code, client)
    held = [y for y in served if year is None or y <= year]
    if not held:
        listed = sorted(served) or "none"
        raise DataProductError(
            f"OCS GE 2.0 has no edition of department {code} up to {year}, and the IGN "
            f"serves {listed}: write a later year, or give the map as a file with "
            'source = "file".'
        )
    return served[max(held)]


def cover_polygons(archive: Path, bbox: tuple[float, float, float, float], covers=None):
    """The cover polygons of the archive inside ``bbox``, EPSG:2154, with their ``code_cs``.

    ``covers`` keeps those codes only; None keeps every cover.
    """
    import geopandas as gpd
    import py7zr

    with py7zr.SevenZipFile(archive) as packed:
        targets = [n for n in packed.getnames() if n.endswith("/OCCUPATION_SOL.gpkg")]
        if not targets:
            raise DataProductError(f"{archive.name} holds no OCCUPATION_SOL layer.")
        with tempfile.TemporaryDirectory(dir=archive.parent) as scratch:
            packed.extract(path=scratch, targets=targets)
            where = None
            if covers is not None:
                listed = ", ".join(f"'{code}'" for code in covers)
                where = f"code_cs IN ({listed})"
            frame = gpd.read_file(
                Path(scratch) / targets[0], bbox=bbox, where=where, columns=["code_cs"]
            )
    return frame.to_crs("EPSG:2154") if frame.crs is not None else frame.set_crs("EPSG:2154")


def archive_folder() -> Path:
    """The folder of the department archives, in the user cache of HydroModPy.

    The archives are raw downloads of about 200 MB that every family reading OCS GE
    (sealed share, infiltration ratio, curve number) and every project share, so they
    live once per machine and not in the data folder of a family.
    """
    from hydromodpy.core.state.portable import cache_dir

    return Path(cache_dir()) / "ocsge"


def department_archives(
    *,
    bbox: tuple[float, float, float, float],
    year: int | None,
    bounds: Bounds | None = None,
) -> tuple[list[Path], list[str]]:
    """The OCS GE archive of each department ``bbox`` meets, downloaded once, and its edition."""
    from filelock import FileLock

    from hydromodpy.catchment.administrative.france import find_departments_in_bbox
    from hydromodpy.core.io.fetch import download, open_client

    codes = find_departments_in_bbox(bbox)
    if not codes:
        raise DataProductError(
            f"No French department meets the box {bbox} (EPSG:2154): OCS GE covers France only."
        )
    folder = archive_folder()
    folder.mkdir(parents=True, exist_ok=True)
    archives, editions = [], []
    with open_client(bounds=bounds) as http:
        for code in codes:
            name = edition(code, year, http)
            editions.append(name)
            archive = folder / f"{name}.7z"
            with FileLock(f"{archive}.lock"):
                if not archive.exists():
                    logger.info("[ocsge] downloading %s", name)
                    download(
                        f"https://data.geopf.fr/telechargement/download/OCSGE/{name}/{name}.7z",
                        archive,
                        bounds=bounds,
                        client=http,
                    )
            archives.append(archive)
    return archives, editions


def ocsge_grid(bbox: tuple[float, float, float, float]):
    """The 10 m grid of ``bbox`` (EPSG:2154): its transform, height and width."""
    import numpy as np
    from rasterio.transform import from_origin

    xmin = np.floor(bbox[0] / PIXEL_M) * PIXEL_M
    ymax = np.ceil(bbox[3] / PIXEL_M) * PIXEL_M
    width = int(np.ceil((bbox[2] - xmin) / PIXEL_M))
    height = int(np.ceil((ymax - bbox[1]) / PIXEL_M))
    return from_origin(xmin, ymax, PIXEL_M, PIXEL_M), height, width


def burn_map(
    target: Path,
    bbox: tuple[float, float, float, float],
    shapes,
    *,
    fill: float,
    editions: list[str],
) -> Path:
    """Burn ``(geometry, value)`` pairs on the 10 m grid of ``bbox`` into ``target`` (nodata -1)."""
    import numpy as np
    import rasterio
    from rasterio.features import rasterize

    from hydromodpy.core.io.atomic_replace import staged_path

    transform, height, width = ocsge_grid(bbox)
    shapes = list(shapes)
    grid = np.full((height, width), fill, dtype="float32")
    if shapes:
        grid = rasterize(
            shapes, out_shape=(height, width), transform=transform, fill=fill, dtype="float32"
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


__all__ = [
    "OCSGE_ORIGIN",
    "PIXEL_M",
    "SEALED_COVERS",
    "archive_folder",
    "burn_map",
    "cover_polygons",
    "department_archives",
    "edition",
    "editions",
    "ocsge_grid",
]
