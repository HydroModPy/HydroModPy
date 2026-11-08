"""Download and cache the BRGM 1:1M national geological map.

Source: http://infoterre.brgm.fr/telechargements/BDCharm50/FR_vecteur.zip
License: ETALAB Open Licence v2.0 (open data, attribution required)
"""

from __future__ import annotations

import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import ClassVar

from filelock import FileLock

from hydromodpy.core.console import progress
from hydromodpy.core.io.atomic_replace import staged_path
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
from hydromodpy.data.variables.geology.apis.fgeol import (
    FGEOL_LAYER_PATTERN,
    bbox_hash,
    find_fgeol_shp,
)

logger = get_logger(__name__)

BRGM_1M_URL = "http://infoterre.brgm.fr/telechargements/BDCharm50/FR_vecteur.zip"


def fetch_brgm_1m(
    *,
    output_dir: Path,
    bbox: tuple[float, float, float, float] | None = None,
    code_field: str = "CODE_LEG",
) -> Path:
    """Download the 1:1M national geological map and save as GeoPackage.

    The 1M map covers all of France. It is stored as-is (no cropping)
    since it is a single national dataset. If a bbox is provided, the
    cached file is cropped at load time.

    Parameters
    ----------
    output_dir : directory for cache storage
    bbox : optional (xmin, ymin, xmax, ymax) in EPSG:2154 for cropping
    code_field : attribute column for geology codes

    Returns
    -------
    Path to the cached GeoPackage file.
    """
    import geopandas as gpd

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Full national file (no crop)
    full_gpkg = output_dir / "geology_brgm_1m_france.gpkg"

    if not full_gpkg.exists():
        zip_path = output_dir / "FR_vecteur.zip"
        # One builder per archive: a second process waits, then reuses it.
        with FileLock(f"{zip_path}.lock"):
            if not full_gpkg.exists():
                _build_national_gpkg(zip_path, full_gpkg)

    # If bbox provided, create a cropped version
    if bbox is not None:
        bbox_h = bbox_hash(bbox)
        cropped_gpkg = output_dir / f"geology_brgm_1m_{bbox_h}.gpkg"

        if not cropped_gpkg.exists():
            from shapely.geometry import box

            with progress.status("Cropping to model area"):
                gdf = gpd.read_file(str(full_gpkg))
                bbox_geom = box(*bbox)
                bbox_gdf = gpd.GeoDataFrame(geometry=[bbox_geom], crs="EPSG:2154")
                gdf = gpd.clip(gdf, bbox_gdf)

                if gdf.empty:
                    raise ValueError(
                        "No geology feature from the 1M map intersects the requested bbox"
                    )
                with staged_path(cropped_gpkg) as staged:
                    gdf.to_file(str(staged), driver="GPKG")
            logger.debug("Cropped 1M map: %s", cropped_gpkg)

        return cropped_gpkg

    return full_gpkg


class Brgm1m:
    """The BRGM 1:1M national geological map, cropped to the request's extent.

    The port class over :func:`fetch_brgm_1m`: the national GeoPackage once, in
    the cache directory the request carries, and a cropped copy when the
    request's box does not cover France. The map is vector geology, so the file
    carries no nodata.
    """

    source_id: ClassVar[str] = "brgm_1m"
    section: ClassVar[str] = "geology"
    payload_kind: ClassVar[PayloadKind] = "files"
    extent_crs: ClassVar[str] = "EPSG:2154"
    selectors: ClassVar[tuple[Selector, ...]] = ("extent",)
    period_need: ClassVar[PeriodNeed] = "refused"
    writes_out_dir: ClassVar[bool] = True

    def __init__(self, *, code_field: str = "CODE_LEG") -> None:
        self.code_field = str(code_field)
        self.variables = ("geology",)
        self.hosts = shipped_hosts(self.source_id)

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Download or crop the map over the request's extent, as one file."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)
        gpkg_path = fetch_brgm_1m(
            output_dir=request.out_dir,
            bbox=extent.bbox,
            code_field=self.code_field,
        )
        from hydromodpy.data.contracts.file_record import FileRecord

        record = FileRecord.of(gpkg_path, state="raw", nodata=None, origin=BRGM_1M_URL)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            files=(record,),
            metadata={"code_field": self.code_field},
        )


def _build_national_gpkg(zip_path: Path, full_gpkg: Path) -> None:
    """Download the national archive if needed and convert it to GeoPackage."""
    import geopandas as gpd

    if not zip_path.exists():
        with (
            progress.task(
                "Downloading BRGM 1:1M geological map", total=None, unit="bytes"
            ) as handle,
            staged_path(zip_path) as staged,
        ):

            def _report(block_count: int, block_size: int, total_size: int) -> None:
                if total_size > 0:
                    handle.update(total=total_size)
                handle.update(completed=block_count * block_size)

            urllib.request.urlretrieve(BRGM_1M_URL, str(staged), reporthook=_report)
        logger.debug("Downloaded: %s", zip_path)

    with tempfile.TemporaryDirectory(prefix="_brgm_1m_extract_", dir=zip_path.parent) as tmp:
        extract_dir = Path(tmp)
        with progress.status("Extracting archive"), zipfile.ZipFile(str(zip_path)) as zf:
            zf.extractall(str(extract_dir))

        shp_path = find_fgeol_shp(extract_dir)
        if shp_path is None:
            raise FileNotFoundError(f"No *{FGEOL_LAYER_PATTERN}.shp found in {extract_dir}")
        logger.debug("Loading shapefile: %s", shp_path.name)

        with progress.status("Converting to GeoPackage"):
            gdf = gpd.read_file(str(shp_path))
            gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()

            if gdf.crs is not None and gdf.crs.to_epsg() != 2154:
                gdf = gdf.to_crs("EPSG:2154")

            with staged_path(full_gpkg) as staged:
                gdf.to_file(str(staged), driver="GPKG")
    logger.debug("Cached national map: %s", full_gpkg)
