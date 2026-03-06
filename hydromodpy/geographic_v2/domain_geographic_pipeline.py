"""Assemble domain-ready geographic artifacts from config + workspace.

This module orchestrates the V2 geographic chain without relying on the
monolithic legacy ``Geographic`` class.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import rasterio

from hydromodpy.domain.surface import Surface
from hydromodpy.geographic_v2.catchment_domain import derive_catchment_domain
from hydromodpy.geographic_v2.catchment_from_point import extract_catchment_from_point
from hydromodpy.geographic_v2.catchment_from_polygon import extract_catchment_from_polygon
from hydromodpy.geographic_v2.catchment_metrics import compute_catchment_area_km2
from hydromodpy.geographic_v2.domain_dem import clip_dem_to_box_buffer
from hydromodpy.geographic_v2.flow_products import build_regional_flow_products
from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.geographic.geographic_paths import GeographicPaths, build_geographic_paths
from hydromodpy.geographic_v2.surface_from_dem import build_surface_topo_from_dem
from hydromodpy.simulation.workspace.workspace import Workspace
from hydromodpy.tools import toolbox


@dataclass(frozen=True)
class DomainGeographicContext:
    """Minimal geographic artifacts consumed by `run_domain_case`."""

    surface_topo: Surface
    watershed_shp: str
    catchment_area_km2: float
    catch_def: str
    x_outlet: float | None
    y_outlet: float | None
    watershed_box_buff_dem: str
    box_buff_shp: str


def _resolve_project_crs(*, dem_init_path: str | Path, crs_project: str | None) -> str | None:
    """Resolve target CRS with explicit config override first."""
    if crs_project is not None:
        return crs_project
    with rasterio.open(str(dem_init_path)) as dem_src:
        epsg = dem_src.crs.to_epsg() if dem_src.crs is not None else None
    return f"EPSG:{epsg}" if epsg is not None else None


def _build_catchment(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
    direc_path: str | Path,
    acc_path: str | Path,
    crs_project: str | None,
) -> None:
    """Build watershed shapefile from outlet coordinates or input polygon."""
    if config.catch_def == "from_outlet_coord":
        if config.x_outlet is None or config.y_outlet is None or config.snap_dist is None:
            raise ValueError(
                "catch_def='from_outlet_coord' requires x_outlet, y_outlet and snap_dist"
            )
        extract_catchment_from_point(
            x_outlet=float(config.x_outlet),
            y_outlet=float(config.y_outlet),
            snap_dist=int(config.snap_dist),
            acc_path=acc_path,
            direc_path=direc_path,
            output_dir=paths.geographic_path,
            crs_project=crs_project,
            outlet_name="outlet.shp",
            outlet_snap_name="outlet_snap.shp",
            watershed_tif_name=Path(paths.watershed).name,
            watershed_shp_name=Path(paths.watershed_shp).name,
        )
        return

    if config.catch_def == "from_polyg_shp":
        if config.polyg_shp_path is None:
            raise ValueError("catch_def='from_polyg_shp' requires polyg_shp_path")
        extract_catchment_from_polygon(
            polyg_shp_path=config.polyg_shp_path,
            output_shp_path=paths.watershed_shp,
            crs_project=crs_project,
        )
        return

    raise ValueError(
        f"Unsupported catch_def for domain pipeline: {config.catch_def!r}. "
        "Supported values: 'from_outlet_coord', 'from_polyg_shp'."
    )


def build_domain_geographic_context(
    *,
    config: GeographicConfig,
    workspace: Workspace,
) -> DomainGeographicContext:
    """
    Build domain-ready geographic outputs from config and workspace.

    The pipeline intentionally focuses on what `run_domain_case` needs:
    - catchment polygon (`watershed.shp`)
    - buffered rectangular support (`watershed_box_buff.shp`)
    - clipped support DEM (`watershed_box_buff_dem.tif`)
    - in-memory topographic `Surface`.
    """
    # Step 1 - Validate mandatory config values.
    if config.dem_init_path is None:
        raise ValueError("geographic.dem_init_path is required")
    if config.buff_area is None:
        raise ValueError("geographic.buff_area is required")

    # Step 2 - Build canonical output paths and folders.
    paths = build_geographic_paths(workspace.catch_folder)
    toolbox.create_folder(paths.geographic_path)
    toolbox.create_folder(paths.correcflow_path)

    # Step 3 - Resolve project CRS.
    dem_init_path = str(config.dem_init_path)
    crs_project = _resolve_project_crs(dem_init_path=dem_init_path, crs_project=config.crs_project)

    # Step 4 - Generate regional flow products on input DEM.
    flow = build_regional_flow_products(
        dem_init_path=dem_init_path,
        dem_out_dir_path=paths.correcflow_path,
        dem_correc_type=str(config.dem_correc_type),
        crs_project=crs_project,
    )

    # Step 5 - Delineate or import catchment polygon.
    _build_catchment(
        config=config,
        paths=paths,
        direc_path=flow.direc,
        acc_path=flow.acc,
        crs_project=crs_project,
    )

    # Step 6 - Compute catchment metrics and derive domain support polygons.
    catchment_area_km2 = compute_catchment_area_km2(paths.watershed_shp)

    derive_catchment_domain(
        catchment_shp=paths.watershed_shp,
        output_dir=paths.geographic_path,
        buff_area=float(config.buff_area),
        dem_init_path=dem_init_path,
        crs_project=crs_project,
        watershed_box_name=Path(paths.watershed_box_shp).name,
        watershed_box_buff_name=Path(paths.box_buff).name,
    )

    # Step 7 - Clip DEM to buffered domain support and build in-memory surface.
    clip_dem_to_box_buffer(
        dem_init_path=dem_init_path,
        box_buff_shp=paths.box_buff,
        output_dem_path=paths.watershed_box_buff_dem,
        crs_project=crs_project,
        nodata=-9999.0,
    )

    surface_topo = build_surface_topo_from_dem(paths.watershed_box_buff_dem)

    # Step 8 - Return compact context consumed by domain pipeline.
    return DomainGeographicContext(
        surface_topo=surface_topo,
        watershed_shp=paths.watershed_shp,
        catchment_area_km2=float(catchment_area_km2),
        catch_def=str(config.catch_def),
        x_outlet=float(config.x_outlet) if config.x_outlet is not None else None,
        y_outlet=float(config.y_outlet) if config.y_outlet is not None else None,
        watershed_box_buff_dem=paths.watershed_box_buff_dem,
        box_buff_shp=paths.box_buff,
    )
