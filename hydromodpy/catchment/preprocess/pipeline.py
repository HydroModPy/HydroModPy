"""Assemble the full geographic artifact set from one config + workspace.

Builds the runtime payload consumed by ``CatchmentDelineation``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hydromodpy.catchment.algorithms.catchment_domain import (
    CatchmentDomainProducts,
    compute_catchment_area_km2,
)
from hydromodpy.catchment.algorithms.dem_metadata import DemMetadata, read_dem_metadata
from hydromodpy.catchment.algorithms.direct_dem_domain import build_direct_dem_domain
from hydromodpy.catchment.algorithms.flow_products import FlowProducts, build_regional_flow_products
from hydromodpy.catchment.algorithms.geographic_paths import GeographicPaths
from hydromodpy.catchment.algorithms.ground_bed import (
    bed_regularization_enabled,
    top_dem_path_from_config,
)
from hydromodpy.catchment.algorithms.ground_corrections import (
    close_notch_report,
    first_pass_channel,
    ground_dem_from_config,
    ground_dem_path_from_config,
    notch_enabled,
    notch_lowered_pixels,
)
from hydromodpy.catchment.algorithms.river_network import (
    RiverNetworkProducts,
    build_river_network_products,
)
from hydromodpy.catchment.algorithms.stream_dem_agreement import report_network_dem_agreement
from hydromodpy.catchment.delineation import resolve_delineation_backend
from hydromodpy.catchment.preprocess.capped_breach_config import capped_breach_of
from hydromodpy.catchment.preprocess.domain_rasters import (
    DomainRasterProducts,
    build_domain_rasters,
)
from hydromodpy.catchment.preprocess.geographic_cache import (
    GeographicProducts,
    clip_regularised_ground,
    load_cached_geographic_products,
    resolve_top_surface_paths,
    write_geographic_cache_manifest,
)
from hydromodpy.catchment.preprocess.geographic_config import GeographicConfig
from hydromodpy.catchment.preprocess.pipeline_steps import (
    build_standard_catchment,
    build_standard_domain_polygons,
    prepare_geographic_run,
)
from hydromodpy.catchment.preprocess.regional_flow_job import copy_regional_flow_from_job
from hydromodpy.core.console import progress
from hydromodpy.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class GeographicRuntimeContext:
    """Compatibility payload produced by geographic preprocessing.

    The context groups canonical paths, regional flow products, clipped rasters,
    DEM metadata, optional river-network products, and area/CRS information.
    ``CatchmentDelineation`` converts it to public runtime attributes through
    ``runtime_attributes``.
    """

    paths: GeographicPaths
    flow_products: FlowProducts
    raster_products: DomainRasterProducts
    dem_metadata: DemMetadata
    river_network_products: RiverNetworkProducts
    catchment_area_km2: float
    top_dem_path: str
    crs_project: str | None
    epsg: int | None
    dem_res: float
    x_outlet: float | None = None
    y_outlet: float | None = None
    x_outlet_snapped: float | None = None
    """Outlet the delineation actually ran from. x_outlet is what the config declared."""

    y_outlet_snapped: float | None = None
    outlet_snap_distance_m: float | None = None
    buffer_distance_m: float | None = None
    """Margin drawn around the catchment, in meters, after rounding to the DEM."""

    buffer_area_increase: float | None = None
    """Relative area the margin added to the catchment; None when not recorded."""

    top_surface_paths: dict[str, str] = field(default_factory=dict)
    """Clips the model top is sampled from, by attribute, where they are not the clips of G.

    Filled by ``[geographic.bed_regularization]`` with the clips of the
    regularized ground, cut by the routine and the polygons that cut the clips
    of G. They replace the clips of G under the same attribute names, and
    ``top_dem_path`` is the regularized ground itself, so the model top and
    the SFR bed read one bed. The routing DEM, the channel tree, the catchment
    and the mesh are built before and do not read them.
    """

    def runtime_attributes(self) -> dict[str, object]:
        """Return the public attribute payload expected from ``CatchmentDelineation``."""
        attrs = dict(vars(self.paths))
        attrs.update(self.top_surface_paths)
        attrs.update(
            {
                "hydrographic_network_generated_shp": self.paths.hydrographic_network_generated_shp,
                "hydrographic_network_generated_summary_json": (
                    self.paths.hydrographic_network_generated_summary_json
                ),
                "catch_area": float(self.catchment_area_km2),
                "crs_proj": self.crs_project,
                "epsg": self.epsg,
                "dem_res": self.dem_res,
                "x_outlet": self.x_outlet,
                "y_outlet": self.y_outlet,
                "x_outlet_snapped": self.x_outlet_snapped,
                "y_outlet_snapped": self.y_outlet_snapped,
                "outlet_snap_distance_m": self.outlet_snap_distance_m,
                "buffer_distance_m": self.buffer_distance_m,
                "buffer_area_increase": self.buffer_area_increase,
                "_paths": self.paths,
                "_dem_metadata": self.dem_metadata,
                "_river_network_products": self.river_network_products,
                "_flow_products": self.flow_products,
                "_top_dem_path": self.top_dem_path,
            }
        )
        attrs.update(self.dem_metadata.runtime_attributes())
        return attrs


@dataclass(frozen=True)
class _Delineation:
    """What one pass of the delineation builds on one routing DEM.

    ``catchment_products`` is None for a ``dem`` domain.
    """

    flow_products: FlowProducts
    catchment_products: object | None
    catchment_area_km2: float
    domain_products: CatchmentDomainProducts
    river_network_products: RiverNetworkProducts


def _delineate(
    *,
    config: GeographicConfig,
    setup: Any,
    tool: object,
    routing_dem_path: str,
) -> _Delineation:
    """Condition, delineate, buffer and extract the network on one routing DEM.

    The first pass routes the ground, the second pass of the crossing notch
    routes the notched ground. The config refuses the notch with a shared
    regional job or a ``dem`` domain, so the second pass always routes and
    delineates here.
    """
    if config.reg_fold is None:
        flow_products = build_regional_flow_products(
            dem_init_path=routing_dem_path,
            dem_out_dir_path=setup.paths.correcflow_path,
            dem_correc_type=str(config.dem_correc_type),
            capped_breach=capped_breach_of(config),
            crs_project=setup.crs_project,
            backend=tool,
            engine_id=config.terrain_engine,
        )
    else:
        flow_products = copy_regional_flow_from_job(
            config=config,
            routing_dem_path=routing_dem_path,
            output_dir=setup.paths.correcflow_path,
            crs_project=setup.crs_project,
            backend=tool,
        )

    catchment_products: object | None = None
    if config.catch_def == "dem":
        dem_products = build_direct_dem_domain(
            dem_init_path=setup.dem_init_path,
            paths=setup.paths,
            crs_project=setup.crs_project,
        )
        catchment_area_km2 = float(dem_products.domain_area_km2)
        domain_products = CatchmentDomainProducts(
            catchment_area_km2=catchment_area_km2,
            buffer_distance_m=0.0,
            watershed_buff_shp=dem_products.watershed_buff_shp,
            watershed_box_shp=dem_products.watershed_box_shp,
            watershed_box_buff_shp=dem_products.watershed_box_buff_shp,
        )
    else:
        catchment_products = build_standard_catchment(
            config=config,
            paths=setup.paths,
            accumulation=flow_products.accumulation,
            crs_project=setup.crs_project,
            backend=tool,
            unsupported_mode="ignore",
        )
        catchment_area_km2 = float(compute_catchment_area_km2(setup.paths.watershed_shp))
        domain_products = build_standard_domain_polygons(
            config=config,
            paths=setup.paths,
            dem_init_path=setup.dem_init_path,
            crs_project=setup.crs_project,
        )

    tool.delineation.polygons_to_lines(
        setup.paths.watershed_shp,
        setup.paths.watershed_contour_shp,
    )

    with progress.status("Extracting river network"):
        river_network_products = build_river_network_products(
            river_network=config.river_network,
            dem_correc_path=flow_products.correc,
            d8_pointer_path=flow_products.direc,
            watershed_shp=setup.paths.watershed_shp,
            geographic_dir=setup.paths.geographic_path,
            correcflow_dir=setup.paths.correcflow_path,
            dem_res_m=float(setup.dem_res),
            streams_tif_path=setup.paths.river_streams_tif,
            streams_pruned_tif_path=setup.paths.river_streams_pruned_tif,
            stream_order_strahler_tif_path=setup.paths.river_stream_order_strahler_tif,
            stream_link_id_tif_path=setup.paths.river_stream_link_id_tif,
            network_shp_path=setup.paths.hydrographic_network_generated_shp,
            summary_json_path=setup.paths.hydrographic_network_generated_summary_json,
            network_crs=setup.crs_project,
            backend=tool,
        )
    return _Delineation(
        flow_products=flow_products,
        catchment_products=catchment_products,
        catchment_area_km2=catchment_area_km2,
        domain_products=domain_products,
        river_network_products=river_network_products,
    )


def _notch_crossings(
    *,
    config: GeographicConfig,
    setup: Any,
    tool: object,
    first: _Delineation,
) -> _Delineation:
    """Notch the ground where the embankments cross the channel tree, then delineate again.

    The channel tree of the first delineation says where the embankments cross
    it. The ground is notched there and the catchment is delineated again on
    it. Every product is then the one of the second pass, the snapped outlet
    too: it is the outlet the final catchment was delineated from.
    """
    channel = first_pass_channel(
        config,
        setup,
        flow=first.flow_products,
        river_products=first.river_network_products,
        catchment_area_km2=first.catchment_area_km2,
    )
    ground = ground_dem_from_config(config, setup, channel=channel)
    delineation = first
    if notch_lowered_pixels(setup) > 0:
        with progress.status("Re-delineating on the notched ground"):
            delineation = _delineate(
                config=config, setup=setup, tool=tool, routing_dem_path=str(ground)
            )
    close_notch_report(setup, catchment_area_km2_after=delineation.catchment_area_km2)
    return delineation


def _build_geographic_products(
    *,
    config: GeographicConfig,
    setup: Any,
    tool: object,
) -> GeographicProducts:
    """Delineate, clip and describe a fresh geographic tree."""
    # The ground is the DEM plus the declared correction (the crossing notch, after
    # the first delineation). The routing chain starts from it, and so does the
    # model top (clipped below), so neither surface sees a structure the other
    # does not.
    ground = ground_dem_from_config(config, setup)
    delineation = _delineate(config=config, setup=setup, tool=tool, routing_dem_path=str(ground))
    if notch_enabled(config):
        delineation = _notch_crossings(config=config, setup=setup, tool=tool, first=delineation)

    with progress.status("Clipping domain rasters"):
        # The model TOP is clipped from the ground: the DEM with the crossings
        # notched, as the routing above saw it.
        raster_products = build_domain_rasters(
            dem_init_path=ground_dem_path_from_config(config, setup),
            correc_path=delineation.flow_products.correc,
            direc_path=delineation.flow_products.direc,
            watershed_shp=setup.paths.watershed_shp,
            watershed_buff_shp=delineation.domain_products.watershed_buff_shp,
            paths=setup.paths,
            crs_project=setup.crs_project,
            backend=tool,
        )
    # The channel bed of the ground, regularized on the channel tree A once A
    # and the catchment are final. Nothing above reads it.
    if bed_regularization_enabled(config):
        with progress.status("Regularising the channel bed of the ground"):
            clip_regularised_ground(
                config=config,
                setup=setup,
                flow_products=delineation.flow_products,
                river_network_products=delineation.river_network_products,
                domain_products=delineation.domain_products,
                tool=tool,
            )
    catchment_products = delineation.catchment_products
    write_geographic_cache_manifest(
        config=config,
        paths=setup.paths,
        domain_products=delineation.domain_products,
        catchment_area_km2=delineation.catchment_area_km2,
        catchment_products=catchment_products,
        flow_products=delineation.flow_products,
        dem_path=setup.dem_init_path,
    )
    # Only the outlet branch snaps; a dem or a polygon domain has no snap to report.
    return GeographicProducts(
        flow_products=delineation.flow_products,
        domain_products=delineation.domain_products,
        raster_products=raster_products,
        river_network_products=delineation.river_network_products,
        catchment_area_km2=delineation.catchment_area_km2,
        x_outlet_snapped=getattr(catchment_products, "x_outlet_snapped", None),
        y_outlet_snapped=getattr(catchment_products, "y_outlet_snapped", None),
        outlet_snap_distance_m=getattr(catchment_products, "snap_distance_m", None),
    )


def build_geographic_runtime_context(
    *,
    config: GeographicConfig,
    out_dir_path: str | Path,
    dem_path: str | Path | None = None,
    backend: object | None = None,
    reuse_existing_outputs: bool | None = None,
    network_map_path: str | Path | None = None,
) -> GeographicRuntimeContext:
    """Build the full geographic runtime context from config and workspace.

    The function prepares regional flow rasters, standard or direct DEM domain
    polygons, clipped domain rasters, DEM metadata, and optional river-network
    products. When cache reuse is enabled, it validates the cache fingerprint
    and reconstructs the same context from existing artifacts.

    ``network_map_path`` is the local vector file of the mapped network, when
    one is declared. It feeds the alpha diagnostic only and never the model.
    """
    setup = prepare_geographic_run(
        config=config,
        out_dir_path=out_dir_path,
        dem_path=dem_path,
    )

    tool = resolve_delineation_backend(backend)
    products = load_cached_geographic_products(
        config=config,
        paths=setup.paths,
        crs_project=setup.crs_project,
        reuse_existing_outputs=reuse_existing_outputs,
        dem_path=setup.dem_init_path,
    )
    if products is None:
        products = _build_geographic_products(config=config, setup=setup, tool=tool)

    # Alpha describes the current map, so it is measured on a cache hit too. The map
    # is not a model input and stays out of the cache fingerprint.
    if config.catch_def != "dem":
        report_network_dem_agreement(
            setup,
            network_map_path=network_map_path,
            d8_pointer_path=products.flow_products.direc,
        )

    dem_metadata = read_dem_metadata(
        watershed_box_buff_dem_path=products.raster_products.watershed_box_buff_dem,
        watershed_buff_dem_path=products.raster_products.watershed_buff_dem,
        watershed_dem_path=products.raster_products.watershed_dem,
        crs_project=setup.crs_project,
    )

    return GeographicRuntimeContext(
        paths=setup.paths,
        flow_products=products.flow_products,
        raster_products=products.raster_products,
        dem_metadata=dem_metadata,
        river_network_products=products.river_network_products,
        catchment_area_km2=products.catchment_area_km2,
        top_dem_path=top_dem_path_from_config(config, setup),
        crs_project=setup.crs_project,
        epsg=setup.epsg,
        dem_res=setup.dem_res,
        x_outlet=(float(config.x_outlet) if config.x_outlet is not None else None),
        y_outlet=(float(config.y_outlet) if config.y_outlet is not None else None),
        x_outlet_snapped=products.x_outlet_snapped,
        y_outlet_snapped=products.y_outlet_snapped,
        outlet_snap_distance_m=products.outlet_snap_distance_m,
        buffer_distance_m=float(products.domain_products.buffer_distance_m),
        buffer_area_increase=products.domain_products.buffer_area_increase,
        top_surface_paths=resolve_top_surface_paths(config, setup.paths),
    )
