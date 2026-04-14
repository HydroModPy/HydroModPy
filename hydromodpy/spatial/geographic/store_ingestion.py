"""Ingest geographic preprocessing outputs into the SimulationCatalog.

Called once per project after :class:`Geographic` processing completes.
Reads rasters (via rasterio) and shapefiles (via geopandas) from the
file-based outputs, then writes them into the catalog (Zarr + DuckDB)
so that downstream consumers can read from the store directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_RASTER_ATTRS = [
    "watershed_box_buff_dem",
    "watershed_box_buff_fill",
    "watershed_box_buff_direc",
    "watershed_buff_dem",
    "watershed_buff_fill",
    "watershed_buff_direc",
    "watershed_dem",
    "watershed_fill",
    "watershed_direc",
    "watershed_contour_tif",
]

_SHAPEFILE_ATTRS = [
    ("watershed", "watershed_shp"),
    ("watershed_box_buff", "box_buff"),
    ("watershed_contour", "watershed_contour_shp"),
]

_RIVER_NETWORK_ATTR = "river_network_shp"
_RIVER_NETWORK_STORE_NAME = "river_network"


def persist_geographic_to_store(
    geographic: Any,
    store: Any,
    *,
    project: str | None = None,
    sim_id: str | None = None,
    cleanup: bool = False,
) -> None:
    """Ingest geographic rasters and metadata into the catalog.

    Parameters
    ----------
    geographic : Geographic
        The geographic object after processing.
    store : SimulationCatalog
        Open catalog for the workspace.
    project : str, optional
        Project name for DuckDB geographic tables. Auto-detected from
        store if not provided.
    sim_id : str, optional
        Simulation UUID for Zarr raster storage. Auto-detected from
        store if not provided.
    cleanup : bool
        If True, delete intermediate geographic directories after ingestion.
    """
    _project = project
    _sim_id = sim_id

    _ingest_rasters(geographic, store, _sim_id)
    _ingest_shapefiles(geographic, store, _project)
    _ingest_river_network(geographic, store, _project)
    _ingest_metadata(geographic, store, _project)

    if cleanup:
        _cleanup_intermediate_dirs(geographic)


def _ingest_rasters(geographic: Any, store: Any, sim_id: str | None) -> None:
    if sim_id is None:
        return

    from hydromodpy.core.backends import get_whitebox_backend

    wb = get_whitebox_backend()

    for attr in _RASTER_ATTRS:
        path = getattr(geographic, attr, None)
        if path is None:
            logger.debug("Skipping raster %s (no path)", attr)
            continue

        name = attr.removesuffix("_tif")

        data = wb.get_cached_raster_numpy(path)
        if data is not None:
            meta = wb.get_cached_raster_metadata(path)
            store.write_geographic_raster(
                sim_id, name, data,
                transform=meta["transform"],
                crs=str(meta.get("crs", "")),
                nodata=float(meta["nodata"]) if meta["nodata"] is not None else -99999.0,
            )
            logger.debug("Ingested raster %s from cache (%s)", name, data.shape)
            continue

        if not Path(path).exists():
            logger.debug("Skipping raster %s (not on disk)", attr)
            continue

        import rasterio
        with rasterio.open(path) as src:
            data = src.read(1)
            transform = tuple(src.transform)[:6]
            crs = str(src.crs) if src.crs else ""
            nodata = float(src.nodata) if src.nodata is not None else -99999.0

        store.write_geographic_raster(
            sim_id, name, data, transform=transform, crs=crs, nodata=nodata,
        )
        logger.debug("Ingested raster %s from disk (%s)", name, data.shape)


def _ingest_shapefiles(geographic: Any, store: Any, project: str | None) -> None:
    if project is None:
        return

    try:
        import geopandas as gpd
    except ImportError:
        logger.debug("geopandas not available, skipping shapefile ingestion")
        return

    for feature_name, attr in _SHAPEFILE_ATTRS:
        path = getattr(geographic, attr, None)
        if path is None or not Path(path).exists():
            logger.debug("Skipping shapefile %s (not found)", feature_name)
            continue

        gdf = gpd.read_file(path)
        if gdf.empty:
            continue

        store.write_geographic_feature(project, feature_name, gdf)
        logger.debug("Ingested feature %s (%d rows)", feature_name, len(gdf))


def _ingest_river_network(geographic: Any, store: Any, project: str | None) -> None:
    if project is None:
        return

    try:
        import geopandas as gpd
    except ImportError:
        logger.debug("geopandas not available, skipping river network ingestion")
        return

    path = getattr(geographic, _RIVER_NETWORK_ATTR, None)
    if path is None:
        products = getattr(geographic, "_river_network_products", None)
        if products is not None:
            path = getattr(products, "network_shp", None)
    if path is None:
        features = getattr(geographic, "get_geographic_derived_features", None)
        if callable(features):
            try:
                derived = features()
                if derived is not None and derived.rivers is not None:
                    path = derived.rivers.network_shp
            except Exception:
                pass

    if path is None or not Path(path).exists():
        logger.debug("Skipping river network (not found)")
        return

    gdf = gpd.read_file(path)
    if gdf.empty:
        return

    store.write_geographic_feature(project, _RIVER_NETWORK_STORE_NAME, gdf)
    logger.debug(
        "Ingested river network (%d segments, %s)",
        len(gdf), gdf.geometry.geom_type.unique().tolist(),
    )


def _ingest_metadata(geographic: Any, store: Any, project: str | None) -> None:
    if project is None:
        return

    metadata = {}

    for key in ("crs_proj", "epsg", "catch_area", "dem_res",
                "x_outlet", "y_outlet", "catch_def", "dem_correc_type"):
        val = getattr(geographic, key, None)
        if val is not None:
            metadata[key] = str(val)

    dem_data = getattr(geographic, "dem_box_buff_data", None)
    if dem_data is not None:
        metadata["nrow"] = str(dem_data.shape[0])
        metadata["ncol"] = str(dem_data.shape[1])

    if metadata:
        store.write_geographic_metadata(project, metadata)
        logger.debug("Ingested %d geographic metadata entries", len(metadata))


def _cleanup_intermediate_dirs(geographic: Any) -> None:
    import shutil

    for attr in ("geographic_path", "correcflow_path"):
        path = getattr(geographic, attr, None)
        if path is not None and Path(path).is_dir():
            shutil.rmtree(path, ignore_errors=True)
            logger.debug("Cleaned up intermediate dir %s", path)

    stable = getattr(geographic, "stable_folder", None)
    if stable is not None:
        stable_path = Path(stable)
        if stable_path.is_dir() and not any(stable_path.iterdir()):
            stable_path.rmdir()
            logger.debug("Removed empty stable folder %s", stable_path)


def dump_cached_rasters_to_disk(geographic: Any) -> None:
    from hydromodpy.core.backends import get_whitebox_backend

    wb = get_whitebox_backend()
    if not wb._raster_cache:
        return

    for path, raster in wb._raster_cache.items():
        wb._ensure_parent(path)
        wb._run_env_operation(
            wb._env.write_raster, raster, path, compress=wb._compress_rasters,
        )
        logger.debug("Dumped cached raster to %s", path)

    logger.info("Wrote %d cached rasters to disk (write_intermediates=True)", len(wb._raster_cache))


def cleanup_stable_folder(geographic: Any) -> None:
    import shutil
    from hydromodpy.core.backends import get_whitebox_backend

    get_whitebox_backend().clear_raster_cache()

    stable = getattr(geographic, "stable_folder", None)
    if stable is not None:
        stable_path = Path(stable)
        if stable_path.is_dir():
            shutil.rmtree(stable_path, ignore_errors=True)
            logger.info("Removed %s — all data is in the project store", stable_path)
