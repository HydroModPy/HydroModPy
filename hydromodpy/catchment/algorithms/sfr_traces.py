"""Delineate the SFR reach trace of each declared network from the river-network products.

Reads the FULL DEM-grid rasters of the river-network products (the clipped rasters
have a different extent), burns the bound lake polygons so the terminal reach is
flagged, and returns one ``SfrReachTrace`` per network. The caller binds them to the
flow; nothing here knows the flow or the run context.
"""

from __future__ import annotations

from collections.abc import Mapping

from hydromodpy.catchment.algorithms.lake_catchments import payload_attr, read_watershed_polygons
from hydromodpy.catchment.algorithms.sfr_network import build_sfr_reach_trace_from_products
from hydromodpy.core.exceptions import ConfigError


def _length_to_m(value: object) -> float:
    to = getattr(value, "to", None)
    if callable(to):
        return float(to("m").magnitude)
    return float(getattr(value, "magnitude", value))  # type: ignore[arg-type]


def build_sfr_reach_traces(
    geographic: object,
    networks: Mapping[str, object],
    lakes: Mapping[str, object],
) -> dict[str, object]:
    """Return one ``SfrReachTrace`` per network id.

    ``geographic`` carries the river-network products, the regional flow products,
    the model-top DEM path and the cell size. ``lakes`` maps lake ids to payloads
    holding a ``polygon``, in the order the solver enumerates them.
    """
    products = getattr(geographic, "_river_network_products", None)
    if products is None or not bool(getattr(products, "enabled", False)):
        raise ConfigError(
            "flow.sinks_sources.sfr needs the river-network products; set "
            "[geographic.river_network] enabled = true."
        )
    link_full = getattr(products, "stream_link_id_full_tif", None)
    if link_full is None:
        raise ConfigError(
            "flow.sinks_sources.sfr needs the stream-link raster; set "
            "[geographic.river_network] compute_stream_links = true."
        )
    flow_products = getattr(geographic, "_flow_products", None)
    if flow_products is None:
        raise ConfigError(
            "flow.sinks_sources.sfr needs the regional flow products (corrected "
            "DEM + D8 pointer); run the geographic preprocessing first."
        )
    # The streambed elevation is read on the model top, never on the routing
    # surface: the routing surface belongs to the flow paths, not to the bed.
    top_dem_tif = getattr(geographic, "_top_dem_path", None)
    if top_dem_tif is None:
        raise ConfigError(
            "flow.sinks_sources.sfr reads the streambed elevation on the model-top "
            "DEM, which the geographic preprocessing publishes; run it first."
        )
    dem_res_m = float(geographic.dem_res)  # type: ignore[attr-defined]
    # Lake polygons in LAK packagedata order (the lakes dict order, which the
    # solver also enumerates): the delineation burns each with its 1-based
    # position so a terminal reach is tagged with the specific lake it feeds.
    lake_polygons = [
        payload_attr(payload, "polygon")
        for payload in lakes.values()
        if payload_attr(payload, "polygon") is not None
    ]
    watershed_polygons = read_watershed_polygons(getattr(geographic, "watershed_shp", None))

    traces: dict[str, object] = {}
    for network_id, payload in networks.items():
        min_slope = payload_attr(payload, "min_slope")
        min_reach_length = payload_attr(payload, "min_reach_length")
        traces[network_id] = build_sfr_reach_trace_from_products(
            stream_link_id_full_tif=str(link_full),
            d8_pointer_tif=str(flow_products.direc),
            flow_acc_cells_tif=str(products.flow_acc_cells_tif),
            top_dem_tif=str(top_dem_tif),
            dem_res_m=dem_res_m,
            stream_order_strahler_full_tif=getattr(
                products, "stream_order_strahler_full_tif", None
            ),
            lake_polygons=lake_polygons,
            watershed_polygons=watershed_polygons,
            min_slope=float(min_slope) if min_slope is not None else 1e-4,
            min_reach_length_m=(
                _length_to_m(min_reach_length) if min_reach_length is not None else 0.0
            ),
        )
    return traces


__all__ = ["build_sfr_reach_traces"]
