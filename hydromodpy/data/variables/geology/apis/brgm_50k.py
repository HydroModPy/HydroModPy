"""Download and cache BRGM 1:50K departmental geological maps.

Source: https://infoterre.brgm.fr/telechargements/BDCharm50/GEO050K_HARM_{dept}.zip
License: ETALAB Open Licence v2.0 (open data, attribution required)

Workflow:
1. Detect which departments overlap the requested bbox
2. Download ZIP for each department
3. Extract and load S_FGEOL shapefiles
4. Merge all departments into one GeoDataFrame
5. Crop to the requested bbox
6. Save as GeoPackage
"""

from __future__ import annotations

import zipfile
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from filelock import FileLock

from hydromodpy.core.console import progress
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
from hydromodpy.data.variables.geology.apis.fgeol import bbox_hash, find_fgeol_shp

if TYPE_CHECKING:
    from hydromodpy.core.runtime.bounds import Bounds

logger = get_logger(__name__)

BRGM_50K_URL_TEMPLATE = (
    "https://infoterre.brgm.fr/telechargements/BDCharm50/GEO050K_HARM_{dept}.zip"
)

BRGM_50K_ORIGIN = "https://infoterre.brgm.fr/telechargements/BDCharm50"
"""The service ``fetch`` answers of, for the :class:`FileRecord` it returns."""


def _download_department(
    dept_code: str,
    *,
    cache_dir: Path,
    bounds: Bounds | None = None,
    client: HTTPClient | None = None,
) -> Path | None:
    """Download and extract one department's geology ZIP.

    Returns path to the extracted S_FGEOL shapefile, or None if unavailable.
    """
    from hydromodpy.catchment.administrative.france import department_code_to_padded

    brgm_code = department_code_to_padded(dept_code)
    url = BRGM_50K_URL_TEMPLATE.format(dept=brgm_code)

    dept_dir = cache_dir / f"GEO050K_HARM_{brgm_code}"
    dept_gpkg = dept_dir / f"geology_50k_{brgm_code}.gpkg"

    # Already extracted and converted
    if dept_gpkg.exists():
        return dept_gpkg

    zip_path = cache_dir / f"GEO050K_HARM_{brgm_code}.zip"
    # One builder per department archive: a second process waits, then reuses it.
    with FileLock(f"{zip_path}.lock"):
        if dept_gpkg.exists():
            return dept_gpkg
        return _build_department_gpkg(
            url,
            zip_path,
            dept_dir,
            dept_gpkg,
            brgm_code,
            bounds=bounds,
            client=client,
        )


def _build_department_gpkg(
    url: str,
    zip_path: Path,
    dept_dir: Path,
    dept_gpkg: Path,
    brgm_code: str,
    *,
    bounds: Bounds | None = None,
    client: HTTPClient | None = None,
) -> Path | None:
    """Download, extract and convert one department archive to GeoPackage."""
    if not zip_path.exists():
        logger.debug("[geology] Downloading 50K map for department %s...", brgm_code)
        try:
            download(url, zip_path, bounds=bounds, client=client)
        except Exception as exc:
            logger.warning("[geology] Failed to download %s: %s", brgm_code, exc)
            return None

    # Extract
    dept_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(str(zip_path)) as zf:
            zf.extractall(str(dept_dir))
    except zipfile.BadZipFile:
        logger.warning("[geology] Bad ZIP for department %s, skipping", brgm_code)
        zip_path.unlink(missing_ok=True)
        return None

    # Find S_FGEOL shapefile
    shp_path = find_fgeol_shp(dept_dir)
    if shp_path is None:
        logger.warning("[geology] No S_FGEOL shapefile in %s", dept_dir)
        return None

    # Convert to GeoPackage for faster future reads
    import geopandas as gpd

    gdf = gpd.read_file(str(shp_path))
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
    if gdf.crs is not None and gdf.crs.to_epsg() != 2154:
        gdf = gdf.to_crs("EPSG:2154")
    with staged_path(dept_gpkg) as staged:
        gdf.to_file(str(staged), driver="GPKG")

    return dept_gpkg


class Brgm50k:
    """The BRGM 1:50K departmental geological maps, merged and cropped.

    The port class over :func:`fetch_brgm_50k`: one GeoPackage of the geo
    logy of the request's extent, the departments it overlaps downloaded and
    merged once each. The map is vector geology, so the file carries no nodata.
    """

    source_id: ClassVar[str] = "brgm_50k"
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
        """Download, merge and crop the map over the request's extent."""
        require_selectors(self, request)
        require_period(self, request)
        extent = extent_for(self, request)
        bounds = getattr(request, "bounds", None)
        with open_client(bounds=bounds) as client:
            gpkg_path = fetch_brgm_50k(
                output_dir=request.out_dir,
                bbox=extent.bbox,
                code_field=self.code_field,
                bounds=bounds,
                client=client,
            )
        from hydromodpy.data.contracts.file_record import FileRecord

        record = FileRecord.of(gpkg_path, state="raw", nodata=None, origin=BRGM_50K_ORIGIN)
        return FetchResult(
            source_id=self.source_id,
            kind=self.payload_kind,
            variables=self.variables,
            extent=extent,
            files=(record,),
            metadata={"code_field": self.code_field},
        )


def fetch_brgm_50k(
    *,
    output_dir: Path,
    bbox: tuple[float, float, float, float],
    code_field: str = "CODE_LEG",
    bounds: Bounds | None = None,
    client: HTTPClient | None = None,
) -> Path:
    """Download, merge, and crop 1:50K departmental geological maps.

    Parameters
    ----------
    output_dir : cache directory
    bbox : (xmin, ymin, xmax, ymax) in EPSG:2154
    code_field : attribute column for geology codes

    Returns
    -------
    Path to the merged and cropped GeoPackage.
    """
    from hydromodpy.catchment.administrative.france import find_departments_in_bbox

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bbox_h = bbox_hash(bbox)
    merged_gpkg = output_dir / f"geology_brgm_50k_{bbox_h}.gpkg"

    if merged_gpkg.exists():
        return merged_gpkg

    # Step 1: find departments
    dept_codes = find_departments_in_bbox(bbox)
    if not dept_codes:
        raise ValueError(
            f"No department found overlapping bbox {bbox}. "
            "Ensure the bbox is in EPSG:2154 (Lambert-93)."
        )
    logger.info("[geology] Departments overlapping bbox: %s", dept_codes)

    # Step 2: download each department
    dept_cache = output_dir / "departments_50k"
    dept_cache.mkdir(parents=True, exist_ok=True)

    import geopandas as gpd
    from shapely.geometry import box

    gdfs = []
    for code in progress.track(dept_codes, "Downloading BRGM 50K departments"):
        dept_path = _download_department(
            code,
            cache_dir=dept_cache,
            bounds=bounds,
            client=client,
        )
        if dept_path is not None:
            gdf = gpd.read_file(str(dept_path))
            gdfs.append(gdf)

    if not gdfs:
        raise ValueError(f"No 50K geology data could be downloaded for departments: {dept_codes}")

    import pandas as pd

    with progress.status("Merging and cropping geological maps"):
        merged = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))
        if merged.crs is None:
            merged = merged.set_crs("EPSG:2154")

        bbox_geom = box(*bbox)
        bbox_gdf = gpd.GeoDataFrame(geometry=[bbox_geom], crs="EPSG:2154")
        merged = gpd.clip(merged, bbox_gdf)

        if merged.empty:
            raise ValueError("No geology feature intersects the requested bbox after merging")

        with staged_path(merged_gpkg) as staged:
            merged.to_file(str(staged), driver="GPKG")
    logger.debug("[geology] Merged 50K geology map: %s", merged_gpkg)

    return merged_gpkg
