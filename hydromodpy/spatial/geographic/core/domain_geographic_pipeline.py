"""Assemble the full geographic context consumed by domain runtime.

Purpose
-------
Orchestrate all geographic core steps and return one compact context object
for ``run_domain_case``.

Design intent
-------------
Keep each operation delegated to focused helpers while exposing one clear,
testable entry point instead of a monolithic preprocessing class.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from hydromodpy.spatial.surface import Surface
from hydromodpy.spatial.geographic.core.catchment_metrics import compute_catchment_area_km2
from hydromodpy.spatial.geographic.core.direct_dem_domain import build_direct_dem_domain
from hydromodpy.spatial.geographic.core.domain_dem import clip_dem_to_box_buffer
from hydromodpy.spatial.geographic.core.flow_products import build_regional_flow_products
from hydromodpy.spatial.geographic.core.pipeline_steps import (
    build_standard_catchment,
    build_standard_domain_polygons,
    prepare_geographic_run,
)
from hydromodpy.spatial.geographic.core.river_network import build_river_network_products
from hydromodpy.spatial.geographic.core.surface_from_dem import build_surface_topo_from_dem
from hydromodpy.core.tools import get_logger

if TYPE_CHECKING:
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
    from hydromodpy.spatial.geographic.core.river_mesh_trace import RiverMeshTrace
    from hydromodpy.core.workspace.workspace import Workspace


logger = get_logger(__name__)


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
    watershed_box_shp:
        Bounding-box support polygon before external buffer.
    box_buff_shp:
        Buffered rectangular support polygon.
    zone_kind:
        ``"catchment"`` for the historical 3-zone raster, ``"uniform"`` for
        direct-DEM domains with no catchment/buffer notion.
    river_mesh_trace:
        Optional in-memory river trace used by river-conformal mesh builders.
    regional_dem_path:
        Full-resolution regional DEM used to contextualize the catchment on
        a broader map when needed.
    """

    surface_topo: Surface
    watershed_shp: str
    catchment_area_km2: float
    catch_def: str
    x_outlet: float | None
    y_outlet: float | None
    watershed_box_buff_dem: str
    watershed_box_shp: str | None
    box_buff_shp: str
    zone_kind: str
    river_mesh_trace: RiverMeshTrace | None = None
    regional_dem_path: str | None = None


def _should_retry_with_fill(*, config: "GeographicConfig", error: Exception) -> bool:
    if str(getattr(config, "catch_def", "")).strip().lower() != "from_outlet_coord":
        return False
    if str(getattr(config, "dem_correc_type", "")).strip().lower() != "breach":
        return False
    return "Watershed delineation produced an empty polygon" in str(error)


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
        from hydromodpy.spatial.geographic.synthetic import build_synthetic_geographic

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
            watershed_box_shp=dem_products.watershed_box_shp,
            box_buff_shp=dem_products.watershed_box_buff_shp,
            zone_kind="uniform",
            regional_dem_path=dem_products.watershed_box_buff_dem,
        )

    if config.buff_area is None:
        raise ValueError("geographic.buff_area is required")

    effective_dem_correc_type = str(config.dem_correc_type)
    flow = build_regional_flow_products(
        dem_init_path=setup.dem_init_path,
        dem_out_dir_path=setup.paths.correcflow_path,
        dem_correc_type=effective_dem_correc_type,
        crs_project=setup.crs_project,
    )

    try:
        build_standard_catchment(
            config=config,
            paths=setup.paths,
            direc_path=flow.direc,
            acc_path=flow.acc,
            direc_data=flow.direc_data,
            acc_data=flow.acc_data,
            crs_project=setup.crs_project,
        )
    except ValueError as exc:
        if not _should_retry_with_fill(config=config, error=exc):
            raise
        logger.warning(
            "Catchment delineation returned an empty polygon with dem_correc_type='breach'; "
            "retrying geographic preprocessing with dem_correc_type='fill'."
        )
        effective_dem_correc_type = "fill"
        flow = build_regional_flow_products(
            dem_init_path=setup.dem_init_path,
            dem_out_dir_path=setup.paths.correcflow_path,
            dem_correc_type=effective_dem_correc_type,
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

    river_network_products = build_river_network_products(
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
        network_crs=setup.crs_project,
    )

    river_mesh_trace = river_network_products.river_mesh_trace

    surface_topo = build_surface_topo_from_dem(setup.paths.watershed_box_buff_dem)

    return DomainGeographicContext(
        surface_topo=surface_topo,
        watershed_shp=setup.paths.watershed_shp,
        catchment_area_km2=float(catchment_area_km2),
        catch_def=str(config.catch_def),
        x_outlet=float(config.x_outlet) if config.x_outlet is not None else None,
        y_outlet=float(config.y_outlet) if config.y_outlet is not None else None,
        watershed_box_buff_dem=setup.paths.watershed_box_buff_dem,
        watershed_box_shp=setup.paths.watershed_box_shp,
        box_buff_shp=setup.paths.box_buff,
        zone_kind="catchment",
        river_mesh_trace=river_mesh_trace,
        regional_dem_path=setup.dem_init_path,
    )

