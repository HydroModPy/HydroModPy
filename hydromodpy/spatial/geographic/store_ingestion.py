"""Ingest geographic preprocessing outputs into the SimulationCatalog.

Called once per project after :class:`CatchmentDelineation` processing completes.
Reads rasters (via rasterio) and shapefiles (via geopandas) from the
file-based outputs, then writes them into the catalog (Zarr + DuckDB)
so that downstream consumers can read from the store directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hydromodpy.core.logging import get_logger
from hydromodpy.spatial.geographic.core.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
    HYDROGRAPHIC_NETWORK_GENERATED_LEGACY_FEATURE_NAME,
)
from hydromodpy.spatial.geographic.geographic_io import (
    backend_has_callables,
    resolve_delineation_backend,
)

logger = get_logger(__name__)

# Only persist final rasters needed for display and derived variables.
# Intermediate WhiteboxTools outputs (buff_direc, buff_dem, etc.) stay
# in memory during processing and are not written to the Zarr store.
_RASTER_ATTRS = [
    "watershed_dem",
    "watershed_fill",
]

_SHAPEFILE_ATTRS = [
    ("watershed", "watershed_shp"),
    ("watershed_box_buff", "box_buff"),
    ("watershed_contour", "watershed_contour_shp"),
]

_GENERATED_HYDROGRAPHIC_NETWORK_ATTR = "hydrographic_network_generated_shp"
_GENERATED_HYDROGRAPHIC_NETWORK_LEGACY_ATTR = "river_network_shp"
_RIVER_NETWORK_STORE_NAME = HYDROGRAPHIC_NETWORK_GENERATED_LEGACY_FEATURE_NAME


def persist_geographic_to_store(
    geographic: Any,
    store: Any,
    *,
    sim_id: str | None = None,
    cleanup: bool = False,
) -> None:
    """Ingest geographic rasters, features and metadata into the catalog.

    All geographic data is scoped by simulation UUID.
    """
    if sim_id is None:
        return

    _ingest_rasters(geographic, store, sim_id)
    _ingest_shapefiles(geographic, store, sim_id)
    _ingest_river_network(geographic, store, sim_id)
    _ingest_metadata(geographic, store, sim_id)

    if cleanup:
        _cleanup_intermediate_dirs(geographic)


def _ingest_rasters(geographic: Any, store: Any, sim_id: str | None) -> None:
    if sim_id is None:
        return

    backend = resolve_delineation_backend()
    raster_backend = getattr(backend, "raster", None)
    has_cache = backend_has_callables(
        backend,
        "raster",
        "get_cached_raster_numpy",
        "get_cached_raster_metadata",
    )

    for attr in _RASTER_ATTRS:
        path = getattr(geographic, attr, None)
        if path is None:
            logger.debug("Skipping raster %s (no path)", attr)
            continue

        name = attr.removesuffix("_tif")

        data = raster_backend.get_cached_raster_numpy(path) if has_cache else None
        if data is not None and raster_backend is not None:
            meta = raster_backend.get_cached_raster_metadata(path)
            store.write_geographic_raster(
                sim_id,
                name,
                data,
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
            sim_id,
            name,
            data,
            transform=transform,
            crs=crs,
            nodata=nodata,
        )
        logger.debug("Ingested raster %s from disk (%s)", name, data.shape)


def _ingest_shapefiles(geographic: Any, store: Any, sim_id: str) -> None:
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

        store.write_geographic_feature(sim_id, feature_name, gdf)
        logger.debug("Ingested feature %s (%d rows)", feature_name, len(gdf))


def _ingest_river_network(geographic: Any, store: Any, sim_id: str) -> None:
    try:
        import geopandas as gpd
    except ImportError:
        logger.debug("geopandas not available, skipping river network ingestion")
        return

    generated_network = None
    generated_network_crs = None
    path = getattr(geographic, _GENERATED_HYDROGRAPHIC_NETWORK_ATTR, None)
    if path is None:
        path = getattr(geographic, _GENERATED_HYDROGRAPHIC_NETWORK_LEGACY_ATTR, None)
    if path is None:
        products = getattr(geographic, "_river_network_products", None)
        if products is not None:
            path = getattr(products, "hydrographic_network_generated_shp", None)
            if path is None:
                path = getattr(products, "network_shp", None)
            generated_network_crs = getattr(products, "network_crs", None)
    features = getattr(geographic, "get_geographic_derived_features", None)
    if callable(features):
        try:
            derived = features()
            if derived is not None:
                generated_network = derived.generated_hydrographic_network
                if path is None and generated_network is not None:
                    path = generated_network.vector_path
                if generated_network is not None:
                    generated_network_crs = generated_network_crs or getattr(
                        generated_network, "crs", None
                    )
                if path is None and derived.rivers is not None:
                    path = (
                        derived.rivers.hydrographic_network_generated_shp
                        or derived.rivers.network_shp
                    )
                if derived.rivers is not None:
                    generated_network_crs = generated_network_crs or getattr(
                        derived.rivers, "network_crs", None
                    )
        except Exception:
            pass

    if path is None or not Path(path).exists():
        logger.debug("Skipping river network (not found)")
        return

    gdf = gpd.read_file(path)
    if gdf.empty:
        return
    if gdf.crs is None and generated_network_crs not in (None, ""):
        gdf = gdf.set_crs(str(generated_network_crs), allow_override=True)

    store.write_geographic_feature(sim_id, _RIVER_NETWORK_STORE_NAME, gdf)
    store.write_geographic_feature(sim_id, HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME, gdf)
    logger.debug(
        "Ingested river network (%d segments, %s)",
        len(gdf),
        gdf.geometry.geom_type.unique().tolist(),
    )


def _ingest_metadata(geographic: Any, store: Any, sim_id: str) -> None:

    metadata = {}

    for key in (
        "crs_proj",
        "epsg",
        "catch_area",
        "dem_res",
        "x_outlet",
        "y_outlet",
        "catch_def",
        "dem_correc_type",
    ):
        val = getattr(geographic, key, None)
        if val is not None:
            metadata[key] = str(val)

    dem_data = getattr(geographic, "dem_box_buff_data", None)
    if dem_data is not None:
        metadata["nrow"] = str(dem_data.shape[0])
        metadata["ncol"] = str(dem_data.shape[1])

    if metadata:
        store.write_geographic_metadata(sim_id, metadata)
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
    backend = resolve_delineation_backend()
    raster_backend = getattr(backend, "raster", None)
    if raster_backend is None or not getattr(raster_backend, "_raster_cache", {}):
        return

    for path, raster in raster_backend._raster_cache.items():
        raster_backend._ensure_parent(path)
        raster_backend._run_env_operation(
            raster_backend._env.write_raster,
            raster,
            path,
            compress=raster_backend._compress_rasters,
        )
        logger.debug("Dumped cached raster to %s", path)

    logger.info(
        "Wrote %d cached rasters to disk (write_intermediates=True)",
        len(raster_backend._raster_cache),
    )


def cleanup_stable_folder(geographic: Any) -> None:
    import shutil

    backend = resolve_delineation_backend()
    if backend_has_callables(backend, "raster", "clear_raster_cache"):
        backend.raster.clear_raster_cache()

    stable = getattr(geographic, "stable_folder", None)
    if stable is not None:
        stable_path = Path(stable)
        if stable_path.is_dir():
            shutil.rmtree(stable_path, ignore_errors=True)
            logger.info("Removed %s - all data is in the project store", stable_path)
