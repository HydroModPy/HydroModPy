"""The river network vector that Whitebox writes, read back as a GeoDataFrame.

It also gives the summary of the network that the diagnostics and the tests
read.
"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import LineString, MultiLineString

from hydromodpy.core.fields.nodata import valid_cells
from hydromodpy.spatial.geographic.core.catchment_domain import catchment_area_m2
from hydromodpy.spatial.geographic.river_network_config import RiverNetworkConfig


def _active_positive_count(path: str | Path) -> int:
    with rasterio.open(str(path)) as src:
        arr = np.asarray(src.read(1))
        nodata = src.nodata
    valid = valid_cells(arr, nodata)
    return int(np.count_nonzero((arr > 0) & valid))


def _max_positive_value(path: str | Path) -> float | None:
    with rasterio.open(str(path)) as src:
        arr = np.asarray(src.read(1))
        nodata = src.nodata
    valid = valid_cells(arr, nodata)
    positive = arr[(arr > 0) & valid]
    if positive.size == 0:
        return None
    return float(np.max(positive))


def _valid_geometry_mask(geometries) -> object:
    return (~geometries.is_empty) & (~geometries.isna())


def _iter_lines_from_whitebox_vector(vector_obj: object) -> list[LineString | MultiLineString]:
    records = list(getattr(vector_obj, "records", ()))
    lines: list[LineString | MultiLineString] = []
    for record in records:
        points = list(getattr(record, "points", ()))
        if len(points) < 2:
            continue
        raw_parts = list(getattr(record, "parts", ()))
        part_starts = sorted(
            {
                int(part_idx)
                for part_idx in raw_parts
                if int(part_idx) >= 0 and int(part_idx) < len(points)
            }
        )
        if not part_starts:
            part_starts = [0]
        if part_starts[0] != 0:
            part_starts = [0, *part_starts]
        part_starts = [*part_starts, int(len(points))]

        parts: list[LineString] = []
        for idx in range(len(part_starts) - 1):
            start = int(part_starts[idx])
            stop = int(part_starts[idx + 1])
            if stop - start < 2:
                continue
            coords = [(float(points[j].x), float(points[j].y)) for j in range(start, stop)]
            if len(coords) >= 2:
                parts.append(LineString(coords))
        if not parts:
            continue
        if len(parts) == 1:
            lines.append(parts[0])
        else:
            lines.append(MultiLineString(parts))
    return lines


def build_network_gdf_from_whitebox_vector(
    *,
    vector_obj: object,
    network_crs: str | None,
) -> gpd.GeoDataFrame:
    projection = str(getattr(vector_obj, "projection", "")).strip()
    if projection == "":
        projection = "" if network_crs is None else str(network_crs).strip()
    crs_value: str | None = projection if projection != "" else None

    geometries = _iter_lines_from_whitebox_vector(vector_obj)
    network_gdf = gpd.GeoDataFrame(geometry=list(geometries), crs=crs_value)
    if not network_gdf.empty:
        network_gdf = network_gdf[_valid_geometry_mask(network_gdf.geometry)].copy()
    return network_gdf


def remove_vector_sidecars(path: str | Path) -> None:
    """Remove one shapefile bundle so stale outputs do not survive empty reruns."""
    shp_path = Path(path)
    if shp_path.suffix.lower() != ".shp":
        if shp_path.exists():
            shp_path.unlink()
        return

    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".fix"):
        sidecar = shp_path.with_suffix(suffix)
        if sidecar.exists():
            sidecar.unlink()


def compute_river_network_summary(
    *,
    river_network: RiverNetworkConfig,
    threshold_cells: float,
    active_streams_tif: str | Path,
    watershed_shp: str | Path,
    stream_order_strahler_tif: str | Path | None,
    network_gdf: gpd.GeoDataFrame | None = None,
) -> dict[str, float | int | bool | str | None]:
    """Compute deterministic summary metrics used by diagnostics and tests."""
    mode = str(river_network.threshold_mode).strip().lower()
    if mode == "area_km2":
        threshold_value = (
            None
            if river_network.threshold_area_km2 is None
            else float(river_network.threshold_area_km2)
        )
    else:
        threshold_value = (
            None if river_network.threshold_cells is None else float(river_network.threshold_cells)
        )

    stream_pixel_count = int(_active_positive_count(active_streams_tif))
    if network_gdf is None:
        network = gpd.GeoDataFrame(geometry=[], crs=None)
    else:
        network = network_gdf
    if not network.empty:
        network = network[_valid_geometry_mask(network.geometry)].copy()
    segment_count = int(len(network))
    network_total_length_m = (
        0.0 if segment_count == 0 else float(np.sum(np.asarray(network.length, dtype=float)))
    )

    catchment_area_km2 = catchment_area_m2(gpd.read_file(str(watershed_shp))) / 1_000_000.0
    drainage_density_km_per_km2 = (
        0.0
        if catchment_area_km2 <= 0.0
        else float((network_total_length_m / 1000.0) / catchment_area_km2)
    )

    max_strahler_order = None
    if stream_order_strahler_tif is not None:
        max_strahler_order = _max_positive_value(stream_order_strahler_tif)

    return {
        "enabled": bool(river_network.enabled),
        "threshold_mode": str(river_network.threshold_mode),
        "threshold_value": threshold_value,
        "threshold_cells": float(threshold_cells),
        "stream_pixel_count": int(stream_pixel_count),
        "segment_count": int(segment_count),
        "network_total_length_m": float(network_total_length_m),
        "max_strahler_order": None if max_strahler_order is None else float(max_strahler_order),
        "catchment_area_km2": float(catchment_area_km2),
        "drainage_density_km_per_km2": float(drainage_density_km_per_km2),
    }
