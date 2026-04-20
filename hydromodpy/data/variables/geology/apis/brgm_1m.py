"""Download and cache the BRGM 1:1M national geological map.

Source: http://infoterre.brgm.fr/telechargements/BDCharm50/FR_vecteur.zip
License: ETALAB Open Licence v2.0 (open data, attribution required)
"""

from __future__ import annotations

import logging
import urllib.request
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

BRGM_1M_URL = "http://infoterre.brgm.fr/telechargements/BDCharm50/FR_vecteur.zip"
FGEOL_LAYER_PATTERN = "S_FGEOL_2154"


def _find_fgeol_shp(extract_dir: Path) -> Path:
    """Find the S_FGEOL shapefile inside the extracted archive."""
    candidates = list(extract_dir.rglob(f"*{FGEOL_LAYER_PATTERN}.shp"))
    if not candidates:
        raise FileNotFoundError(
            f"No *{FGEOL_LAYER_PATTERN}.shp found in {extract_dir}"
        )
    return candidates[0]


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
        logger.info("[geology] Downloading BRGM 1:1M geological map...")
        zip_path = output_dir / "FR_vecteur.zip"

        if not zip_path.exists():
            urllib.request.urlretrieve(BRGM_1M_URL, str(zip_path))
            logger.info("[geology] Downloaded: %s", zip_path)

        extract_dir = output_dir / "_brgm_1m_extract"
        extract_dir.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(str(zip_path)) as zf:
            zf.extractall(str(extract_dir))

        shp_path = _find_fgeol_shp(extract_dir)
        logger.info("[geology] Loading shapefile: %s", shp_path.name)

        gdf = gpd.read_file(str(shp_path))
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()

        if gdf.crs is not None and gdf.crs.to_epsg() != 2154:
            gdf = gdf.to_crs("EPSG:2154")

        gdf.to_file(str(full_gpkg), driver="GPKG")
        logger.info("[geology] Cached national map: %s", full_gpkg)

        # Cleanup extracted files
        import shutil
        shutil.rmtree(str(extract_dir), ignore_errors=True)

    # If bbox provided, create a cropped version
    if bbox is not None:
        bbox_h = _bbox_hash_str(bbox)
        cropped_gpkg = output_dir / f"geology_brgm_1m_{bbox_h}.gpkg"

        if not cropped_gpkg.exists():
            from shapely.geometry import box

            gdf = gpd.read_file(str(full_gpkg))
            bbox_geom = box(*bbox)
            bbox_gdf = gpd.GeoDataFrame(geometry=[bbox_geom], crs="EPSG:2154")
            gdf = gpd.clip(gdf, bbox_gdf)

            if gdf.empty:
                raise ValueError(
                    "No geology feature from the 1M map intersects the requested bbox"
                )
            gdf.to_file(str(cropped_gpkg), driver="GPKG")
            logger.info("[geology] Cropped 1M map: %s", cropped_gpkg)

        return cropped_gpkg

    return full_gpkg


def _bbox_hash_str(bbox: tuple) -> str:
    """Short deterministic hash of a bounding box."""
    import hashlib
    s = f"{bbox[0]:.2f}_{bbox[1]:.2f}_{bbox[2]:.2f}_{bbox[3]:.2f}"
    return hashlib.md5(s.encode()).hexdigest()[:8]
