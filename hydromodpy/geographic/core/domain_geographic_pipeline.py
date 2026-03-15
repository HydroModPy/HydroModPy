"""Assemble all geographic artifacts required by ``run_domain_case``.

This module is the V2 orchestration layer. It delegates each operation to a
focused helper module and returns a compact context payload used by the domain
runtime. The objective is to keep business logic explicit and testable without
the monolithic legacy ``Geographic`` class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hydromodpy.domain.surface import Surface
from hydromodpy.geographic.core.catchment_metrics import compute_catchment_area_km2
from hydromodpy.geographic.core.direct_dem_domain import build_direct_dem_domain
from hydromodpy.geographic.core.domain_dem import clip_dem_to_box_buffer
from hydromodpy.geographic.core.flow_products import build_regional_flow_products
from hydromodpy.geographic.core.pipeline_steps import (
    build_standard_catchment,
    build_standard_domain_polygons,
    prepare_geographic_run,
)
from hydromodpy.geographic.core.river_network import build_river_network_products
from hydromodpy.geographic.core.surface_from_dem import build_surface_topo_from_dem

if TYPE_CHECKING:
    from hydromodpy.geographic.geographic_config import GeographicConfig
    from hydromodpy.simulation.workspace.workspace import Workspace


@dataclass(frozen=True)
class DomainGeographicContext:
    """Geographic payload consumed by the domain execution pipeline.

    Attributes
    ----------
    surface_topo:
        DEM-derived topographic surface on the buffered rectangular support.
    watershed_shp:
        Catchment polygon path (canonical ``watershed.shp`` output).
    catchment_area_km2:
        Catchment area used by domain parameterization.
    catch_def:
        Catchment definition mode from configuration.
    x_outlet, y_outlet:
        Outlet coordinates when catchment is outlet-derived, else ``None``.
    watershed_box_buff_dem:
        DEM clipped to buffered rectangular support.
    box_buff_shp:
        Buffered rectangular support polygon.
    zone_kind:
        ``"catchment"`` for the historical 3-zone raster, ``"uniform"`` for
        direct-DEM domains with no catchment/buffer notion.
    """

    surface_topo: Surface
    watershed_shp: str
    catchment_area_km2: float
    catch_def: str
    x_outlet: float | None
    y_outlet: float | None
    watershed_box_buff_dem: str
    box_buff_shp: str
    zone_kind: str


def build_domain_geographic_context(
    *,
    config: GeographicConfig,
    workspace: Workspace,
) -> DomainGeographicContext:
    """Compute all geographic products required by one domain run.

    The sequence depends on the selected mode:
    - ``synthetic``: build one analytical support and reuse its exported
      compatibility artifacts;
    - ``dem``: derive domain footprint directly from the DEM and build one
      uniform zone support;
    - catchment modes: generate flow rasters, build catchment polygons,
      derive buffered supports, then clip the DEM on the box-buffer support.
    """
    if config.uses_synthetic_geographic():
        from hydromodpy.geographic.synthetic import build_synthetic_geographic

        geographic = build_synthetic_geographic(
            config=config.synthetic,
            output_dir=workspace.stable_folder / "geographic",
            workspace=workspace,
        )
        return geographic.get_domain_geographic_context()

    if config.dem_init_path is None:
        raise ValueError("geographic.dem_init_path is required")

    setup = prepare_geographic_run(
        config=config,
        out_dir_path=workspace.catch_folder,
    )

    if config.catch_def == "dem":
        dem_products = build_direct_dem_domain(
            dem_init_path=setup.dem_init_path,
            paths=setup.paths,
            crs_project=setup.crs_project,
        )
        surface_topo = build_surface_topo_from_dem(dem_products.watershed_box_buff_dem)
        return DomainGeographicContext(
            surface_topo=surface_topo,
            watershed_shp=dem_products.watershed_shp,
            catchment_area_km2=float(dem_products.domain_area_km2),
            catch_def=str(config.catch_def),
            x_outlet=None,
            y_outlet=None,
            watershed_box_buff_dem=dem_products.watershed_box_buff_dem,
            box_buff_shp=dem_products.watershed_box_buff_shp,
            zone_kind="uniform",
        )

    if config.buff_area is None:
        raise ValueError("geographic.buff_area is required")

    flow = build_regional_flow_products(
        dem_init_path=setup.dem_init_path,
        dem_out_dir_path=setup.paths.correcflow_path,
        dem_correc_type=str(config.dem_correc_type),
        crs_project=setup.crs_project,
    )

    build_standard_catchment(
        config=config,
        paths=setup.paths,
        direc_path=flow.direc,
        acc_path=flow.acc,
        direc_data=flow.direc_data,
        acc_data=flow.acc_data,
        crs_project=setup.crs_project,
    )

    catchment_area_km2 = compute_catchment_area_km2(setup.paths.watershed_shp)

    build_standard_domain_polygons(
        config=config,
        paths=setup.paths,
        dem_init_path=setup.dem_init_path,
        crs_project=setup.crs_project,
    )

    clip_dem_to_box_buffer(
        dem_init_path=setup.dem_init_path,
        box_buff_shp=setup.paths.box_buff,
        output_dem_path=setup.paths.watershed_box_buff_dem,
        crs_project=setup.crs_project,
        nodata=-9999.0,
    )

    build_river_network_products(
        river_network=config.river_network,
        dem_correc_path=flow.correc,
        d8_pointer_path=flow.direc,
        watershed_shp=setup.paths.watershed_shp,
        geographic_dir=setup.paths.geographic_path,
        correcflow_dir=setup.paths.correcflow_path,
        dem_res_m=float(setup.dem_res),
        streams_tif_path=setup.paths.river_streams_tif,
        streams_pruned_tif_path=setup.paths.river_streams_pruned_tif,
        stream_order_strahler_tif_path=setup.paths.river_stream_order_strahler_tif,
        stream_link_id_tif_path=setup.paths.river_stream_link_id_tif,
        network_shp_path=setup.paths.river_network_shp,
        summary_json_path=setup.paths.river_network_summary_json,
    )

    surface_topo = build_surface_topo_from_dem(setup.paths.watershed_box_buff_dem)

    return DomainGeographicContext(
        surface_topo=surface_topo,
        watershed_shp=setup.paths.watershed_shp,
        catchment_area_km2=float(catchment_area_km2),
        catch_def=str(config.catch_def),
        x_outlet=float(config.x_outlet) if config.x_outlet is not None else None,
        y_outlet=float(config.y_outlet) if config.y_outlet is not None else None,
        watershed_box_buff_dem=setup.paths.watershed_box_buff_dem,
        box_buff_shp=setup.paths.box_buff,
        zone_kind="catchment",
    )

