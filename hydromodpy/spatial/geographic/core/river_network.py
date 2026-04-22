"""Build DEM-derived river-network products on catchment support.

Purpose
-------
Create optional hydrographic products from flow rasters:
- extracted stream raster,
- vector river network,
- optional stream-order/link diagnostics,
- compact JSON summary for regression checks and reporting.

Pipeline position
-----------------
Executed after catchment/domain preprocessing when
``geographic.river_network.enabled = true``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import geopandas as gpd
import numpy as np
import rasterio
from shapely.geometry import LineString, MultiLineString

from hydromodpy.spatial.delineation import WhiteboxBackend, get_whitebox_backend
from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace
from hydromodpy.spatial.geographic.geographic_config import RiverNetworkConfig

if TYPE_CHECKING:
    from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class RiverNetworkProducts:
    """Canonical output paths and key metrics for one river-network build."""

    enabled: bool
    threshold_cells: float | None = None
    flow_acc_cells_tif: str | None = None
    streams_tif: str | None = None
    active_streams_tif: str | None = None
    streams_pruned_tif: str | None = None
    stream_order_strahler_tif: str | None = None
    stream_link_id_tif: str | None = None
    network_shp: str | None = None
    network_crs: str | None = None
    river_mesh_trace: RiverMeshTrace | None = None
    summary_json: str | None = None


def resolve_stream_threshold_cells(
    *,
    river_network: RiverNetworkConfig,
    dem_res_m: float,
) -> float:
    """Resolve the stream-initiation threshold as contributing cell count."""
    if float(dem_res_m) <= 0.0:
        raise ValueError("dem_res_m must be > 0.")

    mode = str(river_network.threshold_mode).strip().lower()
    if mode == "area_km2":
        area_km2 = river_network.threshold_area_km2
        if area_km2 is None or float(area_km2) <= 0.0:
            raise ValueError("threshold_area_km2 must be > 0 when threshold_mode='area_km2'.")
        return float(area_km2) * 1_000_000.0 / (float(dem_res_m) * float(dem_res_m))

    cells = river_network.threshold_cells
    if cells is None or float(cells) <= 0.0:
        raise ValueError("threshold_cells must be > 0 when threshold_mode='cells'.")
    return float(cells)


def _active_positive_count(path: str | Path) -> int:
    with rasterio.open(str(path)) as src:
        arr = np.asarray(src.read(1))
        nodata = src.nodata
    valid = np.isfinite(arr)
    if nodata is not None:
        valid &= arr != nodata
    return int(np.count_nonzero((arr > 0) & valid))


def _max_positive_value(path: str | Path) -> float | None:
    with rasterio.open(str(path)) as src:
        arr = np.asarray(src.read(1))
        nodata = src.nodata
    valid = np.isfinite(arr)
    if nodata is not None:
        valid &= arr != nodata
    positive = arr[(arr > 0) & valid]
    if positive.size == 0:
        return None
    return float(np.max(positive))


def _valid_geometry_mask(geometries) -> object:
    return (~geometries.is_empty) & (~geometries.isna())


def _iter_line_geometries(geometries: list[BaseGeometry]) -> list[BaseGeometry]:
    out: list[BaseGeometry] = []
    for geometry in geometries:
        if geometry is None:
            continue
        if bool(getattr(geometry, "is_empty", True)):
            continue
        geom_type = str(getattr(geometry, "geom_type", ""))
        if geom_type in {"LineString", "MultiLineString"}:
            out.append(geometry)
            continue
        if geom_type == "GeometryCollection":
            children = list(getattr(geometry, "geoms", ()))
            out.extend(_iter_line_geometries(children))
    return out


def _build_river_mesh_trace_from_network_gdf(
    *,
    network_gdf: gpd.GeoDataFrame,
    network_crs: str | None,
) -> RiverMeshTrace | None:
    if network_gdf.empty:
        return None

    crs = network_gdf.crs
    network_crs_token = None if network_crs is None else str(network_crs).strip()
    if crs is None and network_crs_token:
        network_gdf = network_gdf.set_crs(network_crs_token, allow_override=True)
        crs = network_gdf.crs
    if crs is None:
        return None

    geometries = [geometry for geometry in network_gdf.geometry.tolist() if geometry is not None]
    line_geometries = _iter_line_geometries(geometries)
    if not line_geometries:
        return None

    return RiverMeshTrace.from_geometries(
        source_kind="geographic_generated",
        crs_wkt=crs.to_wkt(),
        geometries=line_geometries,
    )


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


def _build_network_gdf_from_whitebox_vector(
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


def _remove_vector_sidecars(path: str | Path) -> None:
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
    network_shp: str | Path | None,
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
    _ = network_shp
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

    catchment = gpd.read_file(str(watershed_shp))
    catchment_area_m2 = (
        0.0 if catchment.empty else float(np.sum(np.asarray(catchment.area, dtype=float)))
    )
    catchment_area_km2 = float(catchment_area_m2 / 1_000_000.0)
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


def build_river_network_products(
    *,
    river_network: RiverNetworkConfig,
    dem_correc_path: str | Path,
    d8_pointer_path: str | Path,
    watershed_shp: str | Path,
    geographic_dir: str | Path,
    correcflow_dir: str | Path,
    dem_res_m: float,
    streams_tif_path: str | Path,
    streams_pruned_tif_path: str | Path,
    stream_order_strahler_tif_path: str | Path,
    stream_link_id_tif_path: str | Path,
    network_shp_path: str | Path,
    summary_json_path: str | Path,
    network_crs: str | None = None,
    backend: WhiteboxBackend | None = None,
) -> RiverNetworkProducts:
    """Build stream rasters, stream vectors and one summary JSON payload."""
    if not bool(river_network.enabled):
        return RiverNetworkProducts(enabled=False)

    tool = get_whitebox_backend() if backend is None else backend

    geo_dir = Path(geographic_dir)
    correc_dir = Path(correcflow_dir)
    geo_dir.mkdir(parents=True, exist_ok=True)
    correc_dir.mkdir(parents=True, exist_ok=True)

    flow_acc_cells_tif = correc_dir / "dem_acc_cells.tif"
    streams_tif = Path(streams_tif_path)
    streams_pruned_tif = Path(streams_pruned_tif_path)
    stream_order_tif = Path(stream_order_strahler_tif_path)
    stream_link_tif = Path(stream_link_id_tif_path)
    network_shp = Path(network_shp_path)
    summary_json = Path(summary_json_path)
    network_crs_value = None if network_crs is None else str(network_crs).strip()
    if network_crs_value == "":
        network_crs_value = None

    threshold_cells = resolve_stream_threshold_cells(
        river_network=river_network,
        dem_res_m=float(dem_res_m),
    )

    streams_full_tif = correc_dir / "dem_streams_full.tif"
    streams_pruned_full_tif = correc_dir / "dem_streams_pruned_full.tif"
    stream_order_full_tif = correc_dir / "dem_stream_order_strahler_full.tif"
    stream_link_full_tif = correc_dir / "dem_stream_link_id_full.tif"

    tool.d8_flow_accumulation(
        str(dem_correc_path),
        str(flow_acc_cells_tif),
        log=False,
    )
    tool.extract_streams(
        str(flow_acc_cells_tif),
        str(streams_full_tif),
        threshold=float(threshold_cells),
        zero_background=True,
    )
    tool.clip_raster_to_polygon(
        str(streams_full_tif),
        str(watershed_shp),
        str(streams_tif),
        maintain_dimensions=False,
    )

    active_streams_tif = streams_tif
    active_streams_full_tif = streams_full_tif
    output_pruned_tif: str | None = None
    if bool(river_network.prune_short_streams):
        tool.remove_short_streams(
            str(d8_pointer_path),
            str(streams_full_tif),
            str(streams_pruned_full_tif),
            min_length=float(river_network.min_stream_length_m),
        )
        tool.clip_raster_to_polygon(
            str(streams_pruned_full_tif),
            str(watershed_shp),
            str(streams_pruned_tif),
            maintain_dimensions=False,
        )
        active_streams_tif = streams_pruned_tif
        active_streams_full_tif = streams_pruned_full_tif
        output_pruned_tif = str(streams_pruned_tif)

    output_stream_order_tif: str | None = None
    if bool(river_network.compute_strahler_order):
        tool.strahler_stream_order(
            str(d8_pointer_path),
            str(active_streams_full_tif),
            str(stream_order_full_tif),
            zero_background=True,
        )
        tool.clip_raster_to_polygon(
            str(stream_order_full_tif),
            str(watershed_shp),
            str(stream_order_tif),
            maintain_dimensions=False,
        )
        output_stream_order_tif = str(stream_order_tif)

    output_stream_link_tif: str | None = None
    if bool(river_network.compute_stream_links):
        tool.stream_link_identifier(
            str(d8_pointer_path),
            str(active_streams_full_tif),
            str(stream_link_full_tif),
            zero_background=True,
        )
        tool.clip_raster_to_polygon(
            str(stream_link_full_tif),
            str(watershed_shp),
            str(stream_link_tif),
            maintain_dimensions=False,
        )
        output_stream_link_tif = str(stream_link_tif)

    tool_any = tool
    required_in_memory_methods = (
        "read_raster",
        "read_vector",
        "write_vector",
        "raster_streams_to_vector_raster",
        "clip_vector",
    )
    missing_methods = [
        method_name
        for method_name in required_in_memory_methods
        if not hasattr(tool_any, method_name)
    ]
    if missing_methods:
        missing_list = ", ".join(missing_methods)
        raise RuntimeError(
            f"River network generation requires in-memory backend methods; missing: {missing_list}."
        )

    streams_raster_obj = tool_any.read_raster(str(active_streams_full_tif))
    d8_pointer_obj = tool_any.read_raster(str(d8_pointer_path))
    raw_vector_obj = tool_any.raster_streams_to_vector_raster(
        streams_raster_obj,
        d8_pointer_obj,
        all_vertices=bool(river_network.all_vertices),
    )
    watershed_vector_obj = tool_any.read_vector(str(watershed_shp))
    clipped_vector_obj = tool_any.clip_vector(raw_vector_obj, watershed_vector_obj)
    network_gdf = _build_network_gdf_from_whitebox_vector(
        vector_obj=clipped_vector_obj,
        network_crs=network_crs_value,
    )
    output_network_shp: str | None = None
    if network_gdf.empty:
        _remove_vector_sidecars(network_shp)
    else:
        tool_any.write_vector(clipped_vector_obj, str(network_shp))
        output_network_shp = str(network_shp)
    river_mesh_trace = _build_river_mesh_trace_from_network_gdf(
        network_gdf=network_gdf,
        network_crs=network_crs_value,
    )

    summary = compute_river_network_summary(
        river_network=river_network,
        threshold_cells=float(threshold_cells),
        active_streams_tif=str(active_streams_tif),
        watershed_shp=watershed_shp,
        network_shp=output_network_shp,
        stream_order_strahler_tif=output_stream_order_tif,
        network_gdf=network_gdf,
    )
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    with summary_json.open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=True)
        stream.write("\n")

    return RiverNetworkProducts(
        enabled=True,
        threshold_cells=float(threshold_cells),
        flow_acc_cells_tif=str(flow_acc_cells_tif),
        streams_tif=str(streams_tif),
        active_streams_tif=str(active_streams_tif),
        streams_pruned_tif=output_pruned_tif,
        stream_order_strahler_tif=output_stream_order_tif,
        stream_link_id_tif=output_stream_link_tif,
        network_shp=output_network_shp,
        network_crs=network_crs_value,
        river_mesh_trace=river_mesh_trace,
        summary_json=str(summary_json),
    )
