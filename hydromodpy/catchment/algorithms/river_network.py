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
from typing import TYPE_CHECKING, Any

from hydromodpy.catchment.algorithms.river_mesh_trace import (
    RiverMeshTrace,
    build_river_mesh_trace_from_network_gdf,
)
from hydromodpy.catchment.algorithms.river_network_config import RiverNetworkConfig
from hydromodpy.catchment.algorithms.river_network_vector import (
    build_network_gdf_from_whitebox_vector,
    compute_river_network_summary,
    remove_vector_sidecars,
)
from hydromodpy.catchment.delineation import (
    backend_has_callables,
    resolve_delineation_backend,
)

if TYPE_CHECKING:
    import geopandas as gpd


@dataclass(frozen=True)
class RiverNetworkProducts:
    """Technical bundle for one DEM-derived network build.

    The canonical conceptual object is now :class:`HydrographicNetwork`, but
    this bundle remains the low-level output contract produced directly by the
    ``geographic.river_network`` preprocessing step and consumed by runtime
    layers.
    """

    enabled: bool
    threshold_cells: float | None = None
    flow_acc_cells_tif: str | None = None
    streams_tif: str | None = None
    active_streams_tif: str | None = None
    streams_pruned_tif: str | None = None
    stream_order_strahler_tif: str | None = None
    stream_link_id_tif: str | None = None
    hydrographic_network_generated_shp: str | None = None
    network_crs: str | None = None
    river_mesh_trace: RiverMeshTrace | None = None
    hydrographic_network_generated_summary_json: str | None = None
    # Full DEM-grid rasters (uncut, same affine/shape as the corrected DEM and
    # the D8 pointer). The SFR delineation needs these, NOT the clipped rasters
    # above whose extent differs.
    stream_order_strahler_full_tif: str | None = None
    stream_link_id_full_tif: str | None = None


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
    backend: object | None = None,
) -> RiverNetworkProducts:
    """Build stream rasters, stream vectors and one summary JSON payload.

    Four steps: the stream rasters, their order and link diagnostics, the
    vector network with its mesh trace, and the summary JSON.
    """
    if not bool(river_network.enabled):
        return RiverNetworkProducts(enabled=False)

    tool = _raster_backend(backend)

    geo_dir = Path(geographic_dir)
    correc_dir = Path(correcflow_dir)
    geo_dir.mkdir(parents=True, exist_ok=True)
    correc_dir.mkdir(parents=True, exist_ok=True)

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

    # Each input is read once and every step chains on the rasters in memory.
    # Each product is still written, because other modules read it.
    inputs = _NetworkInputs(
        dem_correc=tool.raster.read_raster(str(dem_correc_path)),
        d8_pointer=tool.raster.read_raster(str(d8_pointer_path)),
        watershed=tool.raster.read_vector(str(watershed_shp)),
    )
    streams = _stream_rasters(
        tool,
        river_network=river_network,
        inputs=inputs,
        correc_dir=correc_dir,
        threshold_cells=threshold_cells,
        streams_tif=streams_tif,
        streams_pruned_tif=streams_pruned_tif,
    )
    stream_order_full_tif = correc_dir / "dem_stream_order_strahler_full.tif"
    stream_link_full_tif = correc_dir / "dem_stream_link_id_full.tif"
    output_stream_order_tif, output_stream_link_tif = _stream_diagnostics(
        tool,
        river_network=river_network,
        inputs=inputs,
        active_streams_full=streams.active_full,
        stream_order_full_tif=stream_order_full_tif,
        stream_link_full_tif=stream_link_full_tif,
        stream_order_tif=stream_order_tif,
        stream_link_tif=stream_link_tif,
    )
    network_gdf, output_network_shp, river_mesh_trace = _vector_network(
        tool,
        river_network=river_network,
        inputs=inputs,
        active_streams_full=streams.active_full,
        network_shp=network_shp,
        network_crs=network_crs_value,
    )
    _write_summary(
        summary_json,
        river_network=river_network,
        threshold_cells=threshold_cells,
        active_streams_tif=streams.active_tif,
        watershed_shp=watershed_shp,
        stream_order_strahler_tif=output_stream_order_tif,
        network_gdf=network_gdf,
    )

    return RiverNetworkProducts(
        enabled=True,
        threshold_cells=float(threshold_cells),
        flow_acc_cells_tif=str(streams.flow_acc_cells_tif),
        streams_tif=str(streams_tif),
        active_streams_tif=str(streams.active_tif),
        streams_pruned_tif=streams.pruned_tif,
        stream_order_strahler_tif=output_stream_order_tif,
        stream_link_id_tif=output_stream_link_tif,
        hydrographic_network_generated_shp=output_network_shp,
        network_crs=network_crs_value,
        river_mesh_trace=river_mesh_trace,
        hydrographic_network_generated_summary_json=str(summary_json),
        stream_order_strahler_full_tif=(
            str(stream_order_full_tif) if bool(river_network.compute_strahler_order) else None
        ),
        stream_link_id_full_tif=(
            str(stream_link_full_tif) if bool(river_network.compute_stream_links) else None
        ),
    )


def _raster_backend(backend: object | None) -> Any:
    """Resolve the delineation backend, refusing one without the raster APIs."""
    tool = resolve_delineation_backend(backend)
    if not (
        backend_has_callables(
            tool,
            "raster",
            "read_raster",
            "read_vector",
            "write_raster",
            "clip_raster_to_polygon_raster",
            "clip_vector",
            "write_vector",
        )
        and backend_has_callables(
            tool,
            "flow",
            "d8_flow_accumulation_raster",
        )
        and backend_has_callables(
            tool,
            "delineation",
            "extract_streams_raster",
            "raster_streams_to_vector_raster",
        )
    ):
        raise TypeError("River network extraction requires a delineation backend with raster APIs.")
    return tool


@dataclass(frozen=True)
class _NetworkInputs:
    """The corrected DEM, the D8 pointer and the watershed, read once."""

    dem_correc: Any
    d8_pointer: Any
    watershed: Any


@dataclass(frozen=True)
class _StreamRasters:
    """The stream rasters of the first step, and the active pair the next steps read."""

    flow_acc_cells_tif: Path
    active_tif: Path
    active_full: Any
    pruned_tif: str | None


def _write_clipped(
    tool: Any, raster: Any, inputs: _NetworkInputs, full: Path, clipped: Path
) -> None:
    """Write a full-grid raster, then its clip to the watershed."""
    tool.raster.write_raster(raster, str(full))
    tool.raster.write_raster(
        tool.raster.clip_raster_to_polygon_raster(
            raster, inputs.watershed, maintain_dimensions=False
        ),
        str(clipped),
    )


def _stream_rasters(
    tool: Any,
    *,
    river_network: RiverNetworkConfig,
    inputs: _NetworkInputs,
    correc_dir: Path,
    threshold_cells: float,
    streams_tif: Path,
    streams_pruned_tif: Path,
) -> _StreamRasters:
    """Accumulate the flow, extract the streams, prune them when asked, clip each."""
    flow_acc_cells_tif = correc_dir / "dem_acc_cells.tif"
    streams_full_tif = correc_dir / "dem_streams_full.tif"
    streams_pruned_full_tif = correc_dir / "dem_streams_pruned_full.tif"

    accumulation = tool.flow.d8_flow_accumulation_raster(inputs.dem_correc, log=False)
    tool.raster.write_raster(accumulation, str(flow_acc_cells_tif))
    streams_full = tool.delineation.extract_streams_raster(
        accumulation,
        threshold=float(threshold_cells),
        zero_background=True,
    )
    _write_clipped(tool, streams_full, inputs, streams_full_tif, streams_tif)

    active_streams_tif = streams_tif
    active_streams_full = streams_full
    output_pruned_tif: str | None = None
    if bool(river_network.prune_short_streams):
        active_streams_full = tool.delineation.remove_short_streams_raster(
            inputs.d8_pointer,
            streams_full,
            min_length=float(river_network.min_stream_length_m),
        )
        _write_clipped(
            tool, active_streams_full, inputs, streams_pruned_full_tif, streams_pruned_tif
        )
        active_streams_tif = streams_pruned_tif
        output_pruned_tif = str(streams_pruned_tif)
    return _StreamRasters(
        flow_acc_cells_tif=flow_acc_cells_tif,
        active_tif=active_streams_tif,
        active_full=active_streams_full,
        pruned_tif=output_pruned_tif,
    )


def _stream_diagnostics(
    tool: Any,
    *,
    river_network: RiverNetworkConfig,
    inputs: _NetworkInputs,
    active_streams_full: Any,
    stream_order_full_tif: Path,
    stream_link_full_tif: Path,
    stream_order_tif: Path,
    stream_link_tif: Path,
) -> tuple[str | None, str | None]:
    """Write the Strahler order and the link ids when asked, return the clipped paths."""
    output_stream_order_tif: str | None = None
    if bool(river_network.compute_strahler_order):
        order = tool.delineation.strahler_stream_order_raster(
            inputs.d8_pointer,
            active_streams_full,
            zero_background=True,
        )
        _write_clipped(tool, order, inputs, stream_order_full_tif, stream_order_tif)
        output_stream_order_tif = str(stream_order_tif)

    output_stream_link_tif: str | None = None
    if bool(river_network.compute_stream_links):
        links = tool.delineation.stream_link_identifier_raster(
            inputs.d8_pointer,
            active_streams_full,
            zero_background=True,
        )
        _write_clipped(tool, links, inputs, stream_link_full_tif, stream_link_tif)
        output_stream_link_tif = str(stream_link_tif)
    return output_stream_order_tif, output_stream_link_tif


def _vector_network(
    tool: Any,
    *,
    river_network: RiverNetworkConfig,
    inputs: _NetworkInputs,
    active_streams_full: Any,
    network_shp: Path,
    network_crs: str | None,
) -> tuple[gpd.GeoDataFrame, str | None, RiverMeshTrace | None]:
    """Vectorize the active streams, clip them, write the shapefile and build the mesh trace.

    An empty network writes no shapefile and removes a stale one. The Whitebox
    vector often carries no projection, so the shapefile gets the ``.prj`` of
    the CRS it was read in when the backend wrote none: a reuse of the tree
    needs it.
    """
    raw_vector_obj = tool.delineation.raster_streams_to_vector_raster(
        active_streams_full,
        inputs.d8_pointer,
        all_vertices=bool(river_network.all_vertices),
    )
    clipped_vector_obj = tool.raster.clip_vector(raw_vector_obj, inputs.watershed)
    network_gdf = build_network_gdf_from_whitebox_vector(
        vector_obj=clipped_vector_obj,
        network_crs=network_crs,
    )
    output_network_shp: str | None = None
    if network_gdf.empty:
        remove_vector_sidecars(network_shp)
    else:
        tool.raster.write_vector(clipped_vector_obj, str(network_shp))
        prj = Path(network_shp).with_suffix(".prj")
        if network_gdf.crs is not None and not prj.exists():
            prj.write_text(network_gdf.crs.to_wkt("WKT1_ESRI"), encoding="utf-8")
        output_network_shp = str(network_shp)
    river_mesh_trace = build_river_mesh_trace_from_network_gdf(
        network_gdf=network_gdf,
        network_crs=network_crs,
    )
    return network_gdf, output_network_shp, river_mesh_trace


def _write_summary(
    summary_json: Path,
    *,
    river_network: RiverNetworkConfig,
    threshold_cells: float,
    active_streams_tif: Path,
    watershed_shp: str | Path,
    stream_order_strahler_tif: str | None,
    network_gdf: gpd.GeoDataFrame,
) -> None:
    """Write the summary JSON of the network."""
    summary = compute_river_network_summary(
        river_network=river_network,
        threshold_cells=float(threshold_cells),
        active_streams_tif=str(active_streams_tif),
        watershed_shp=watershed_shp,
        stream_order_strahler_tif=stream_order_strahler_tif,
        network_gdf=network_gdf,
    )
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    with summary_json.open("w", encoding="utf-8") as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=True)
        stream.write("\n")
