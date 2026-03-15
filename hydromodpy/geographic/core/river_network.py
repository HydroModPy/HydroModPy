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

from dataclasses import dataclass
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio

from hydromodpy.backends import WhiteboxBackend, get_whitebox_backend
from hydromodpy.geographic.geographic_config import RiverNetworkConfig


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


def compute_river_network_summary(
    *,
    river_network: RiverNetworkConfig,
    threshold_cells: float,
    active_streams_tif: str | Path,
    watershed_shp: str | Path,
    network_shp: str | Path,
    stream_order_strahler_tif: str | Path | None,
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
        threshold_value = None if river_network.threshold_cells is None else float(river_network.threshold_cells)

    stream_pixel_count = int(_active_positive_count(active_streams_tif))

    network = gpd.read_file(str(network_shp))
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

    raw_network_shp = geo_dir / "_river_network_raw.shp"
    tool.raster_streams_to_vector(
        str(active_streams_full_tif),
        str(d8_pointer_path),
        str(raw_network_shp),
        all_vertices=bool(river_network.all_vertices),
    )
    tool.clip(str(raw_network_shp), str(watershed_shp), str(network_shp))

    summary = compute_river_network_summary(
        river_network=river_network,
        threshold_cells=float(threshold_cells),
        active_streams_tif=str(active_streams_tif),
        watershed_shp=watershed_shp,
        network_shp=str(network_shp),
        stream_order_strahler_tif=output_stream_order_tif,
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
        network_shp=str(network_shp),
        summary_json=str(summary_json),
    )
