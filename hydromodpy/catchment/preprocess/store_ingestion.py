"""Ingest geographic preprocessing outputs into the Catalog.

Called once per project after :class:`CatchmentDelineation` processing completes.
Reads rasters (via rasterio) and shapefiles (via geopandas) from the
file-based outputs, then writes them into the catalog (Zarr + DuckDB)
so that downstream consumers can read from the store directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import geopandas as gpd
import rasterio

from hydromodpy.catchment.algorithms.hydrographic_network import (
    HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME,
)
from hydromodpy.catchment.preprocess.capped_breach_config import capped_breach_of
from hydromodpy.core.fields.nodata import RASTER_NODATA
from hydromodpy.core.io.crs import crs_text
from hydromodpy.core.logging import get_logger

if TYPE_CHECKING:
    import numpy as np

from hydromodpy.catchment.preprocess.preprocessing_cleanup import cleanup_intermediate_dirs

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
        cleanup_intermediate_dirs(geographic)


def read_raster_data_and_meta(
    path: str | Path,
) -> tuple[np.ndarray, tuple[float, ...], float | None, str] | None:
    """Read band 1 of a raster from disk.

    Returns ``(data, transform, nodata, crs)``, or None when the file is not on
    disk. ``transform`` is the affine ``(a, b, c, d, e, f)`` the store takes.
    ``nodata`` is None and ``crs`` is ``""`` when the raster declares none.
    """
    path_str = str(path)
    if not Path(path_str).exists():
        return None
    with rasterio.open(path_str) as src:
        # The store's crs is a text field, so a raster without CRS gives "".
        return src.read(1), tuple(src.transform)[:6], src.nodata, crs_text(src.crs) or ""


def _ingest_rasters(geographic: Any, store: Any, sim_id: str | None) -> None:
    if sim_id is None:
        return

    for attr in _RASTER_ATTRS:
        path = getattr(geographic, attr, None)
        if path is None:
            logger.debug("Skipping raster %s (no path)", attr)
            continue
        raster = read_raster_data_and_meta(path)
        if raster is None:
            logger.debug("Skipping raster %s (not on disk)", attr)
            continue
        data, transform, nodata, crs = raster
        name = attr.removesuffix("_tif")
        # A raster that declares no nodata takes the one of the DEM it sits
        # beside in the geographic group, so the group reads with one sentinel.
        store.write_geographic_raster(
            sim_id,
            name,
            data,
            transform=transform,
            crs=crs,
            nodata=float(nodata) if nodata is not None else RASTER_NODATA,
        )
        logger.debug("Ingested raster %s (%s)", name, data.shape)


def _ingest_shapefiles(geographic: Any, store: Any, sim_id: str) -> None:
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
    generated_network = None
    generated_network_crs = None
    path = getattr(geographic, _GENERATED_HYDROGRAPHIC_NETWORK_ATTR, None)
    if path is None:
        products = getattr(geographic, "_river_network_products", None)
        if products is not None:
            path = getattr(products, "hydrographic_network_generated_shp", None)
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
                    path = derived.rivers.hydrographic_network_generated_shp
                if derived.rivers is not None:
                    generated_network_crs = generated_network_crs or getattr(
                        derived.rivers, "network_crs", None
                    )
        except Exception as exc:
            logger.debug("The generated river network could not be read off the features: %s", exc)

    if path is None or not Path(path).exists():
        logger.debug("Skipping river network (not found)")
        return

    gdf = gpd.read_file(path)
    if gdf.empty:
        return
    if gdf.crs is None:
        fallback_crs = generated_network_crs or _geographic_crs(geographic)
        if fallback_crs not in (None, ""):
            gdf = gdf.set_crs(str(fallback_crs), allow_override=True)

    store.write_geographic_feature(sim_id, HYDROGRAPHIC_NETWORK_GENERATED_FEATURE_NAME, gdf)
    logger.debug(
        "Ingested river network (%d segments, %s)",
        len(gdf),
        gdf.geometry.geom_type.unique().tolist(),
    )


def _geographic_crs(geographic: Any) -> str | None:
    """Return the best CRS declared on a geographic runtime object."""
    for attr in ("crs_proj", "crs_project", "crs"):
        value = getattr(geographic, attr, None)
        if value not in (None, ""):
            return str(value)
    epsg = getattr(geographic, "epsg", None)
    if epsg not in (None, ""):
        return f"EPSG:{epsg}"
    return None


def _ingest_metadata(geographic: Any, store: Any, sim_id: str) -> None:

    metadata = {}

    for key in (
        "crs_proj",
        "epsg",
        "catch_area",
        "dem_res",
        "x_outlet",
        "y_outlet",
        # The declared pour point is not the one the catchment came from: the
        # snap moves it onto the strongest accumulation cell within snap_dist.
        # Persisting both is what lets a figure mark the right star and a reader
        # see how far the two are apart.
        "x_outlet_snapped",
        "y_outlet_snapped",
        "outlet_snap_distance_m",
        "catch_def",
        "dem_correc_type",
        # The two undrained counts of a conditioned DEM, from the product the
        # run read. A raw DEM has none, so a raw run records no key here.
        "dem_cells_without_descent",
        "dem_strict_pits",
    ):
        val = getattr(geographic, key, None)
        if val is not None:
            metadata[key] = str(val)

    # The limits exist only for the method that reads them, so a fill or a breach
    # run records none rather than a default nobody applied.
    capped = capped_breach_of(geographic)
    if capped is not None:
        metadata["capped_breach_max_depth_m"] = str(capped.max_depth_m)
        metadata["capped_breach_max_distance_m"] = str(capped.max_distance_m)
        # What the limits produced, read from the flow products the run kept (or
        # read back from the cache description on a cache hit).
        flow_products = getattr(geographic, "_flow_products", None)
        report = (
            flow_products.accumulation.directions.conditioned_dem.breach_report
            if flow_products is not None
            else None
        )
        if report is not None:
            for key, value in report.to_document().items():
                metadata[f"capped_breach_realised_{key}"] = str(value)

    dem_data = getattr(geographic, "dem_box_buff_data", None)
    if dem_data is not None:
        metadata["nrow"] = str(dem_data.shape[0])
        metadata["ncol"] = str(dem_data.shape[1])

    if metadata:
        store.write_geographic_metadata(sim_id, metadata)
        logger.debug("Ingested %d geographic metadata entries", len(metadata))
