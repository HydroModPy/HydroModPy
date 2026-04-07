"""Download and cache BRGM 1:50K departmental geological maps.

Source: http://infoterre.brgm.fr/telechargements/BDCharm50/GEO050K_HARM_{dept}.zip
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

import hashlib
import io
import logging
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

import geopandas as gpd
from shapely.geometry import box

BRGM_50K_URL_TEMPLATE = (
    "http://infoterre.brgm.fr/telechargements/BDCharm50/GEO050K_HARM_{dept}.zip"
)
FGEOL_LAYER_PATTERN = "S_FGEOL_2154"


def _bbox_hash_str(bbox: tuple) -> str:
    s = f"{bbox[0]:.2f}_{bbox[1]:.2f}_{bbox[2]:.2f}_{bbox[3]:.2f}"
    return hashlib.md5(s.encode()).hexdigest()[:8]


def _find_fgeol_shp(extract_dir: Path) -> Path | None:
    """Find the S_FGEOL shapefile inside extracted department archive."""
    candidates = list(extract_dir.rglob(f"*{FGEOL_LAYER_PATTERN}.shp"))
    return candidates[0] if candidates else None


def _download_department(
    dept_code: str,
    *,
    cache_dir: Path,
) -> Path | None:
    """Download and extract one department's geology ZIP.

    Returns path to the extracted S_FGEOL shapefile, or None if unavailable.
    """
    from hydromodpy.data.common.administrative.france import (
        department_code_to_brgm_code,
    )

    brgm_code = department_code_to_brgm_code(dept_code)
    url = BRGM_50K_URL_TEMPLATE.format(dept=brgm_code)

    dept_dir = cache_dir / f"GEO050K_HARM_{brgm_code}"
    dept_gpkg = dept_dir / f"geology_50k_{brgm_code}.gpkg"

    # Already extracted and converted
    if dept_gpkg.exists():
        return dept_gpkg

    zip_path = cache_dir / f"GEO050K_HARM_{brgm_code}.zip"

    # Download ZIP
    if not zip_path.exists():
        logger.info("[geology] Downloading 50K map for department %s...", brgm_code)
        try:
            urllib.request.urlretrieve(url, str(zip_path))
        except urllib.error.HTTPError as exc:
            logger.warning("[geology] Department %s not available: %s", brgm_code, exc)
            return None
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
    shp_path = _find_fgeol_shp(dept_dir)
    if shp_path is None:
        logger.warning("[geology] No S_FGEOL shapefile in %s", dept_dir)
        return None

    # Convert to GeoPackage for faster future reads
    gdf = gpd.read_file(str(shp_path))
    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
    if gdf.crs is not None and gdf.crs.to_epsg() != 2154:
        gdf = gdf.to_crs("EPSG:2154")
    gdf.to_file(str(dept_gpkg), driver="GPKG")

    return dept_gpkg


def fetch_brgm_50k(
    *,
    output_dir: Path,
    bbox: tuple[float, float, float, float],
    code_field: str = "CODE_LEG",
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
    from hydromodpy.data.common.administrative.france import (
        find_departments_in_bbox,
    )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bbox_h = _bbox_hash_str(bbox)
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

    gdfs = []
    for code in dept_codes:
        dept_path = _download_department(code, cache_dir=dept_cache)
        if dept_path is not None:
            gdf = gpd.read_file(str(dept_path))
            gdfs.append(gdf)

    if not gdfs:
        raise ValueError(
            f"No 50K geology data could be downloaded for departments: {dept_codes}"
        )

    # Step 3: merge all departments
    import pandas as pd
    merged = gpd.GeoDataFrame(pd.concat(gdfs, ignore_index=True))
    if merged.crs is None:
        merged = merged.set_crs("EPSG:2154")

    # Step 4: crop to bbox
    bbox_geom = box(*bbox)
    bbox_gdf = gpd.GeoDataFrame(geometry=[bbox_geom], crs="EPSG:2154")
    merged = gpd.clip(merged, bbox_gdf)

    if merged.empty:
        raise ValueError("No geology feature intersects the requested bbox after merging")

    # Step 5: save
    merged.to_file(str(merged_gpkg), driver="GPKG")
    logger.info("[geology] Merged 50K geology map: %s", merged_gpkg)

    return merged_gpkg
