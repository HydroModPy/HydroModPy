"""Assemble the full legacy geographic artifact set from one config + workspace."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from geopy.geocoders import Nominatim

from hydromodpy.backends import WhiteboxBackend, get_whitebox_backend
from hydromodpy.geographic.geographic_config import GeographicConfig
from hydromodpy.geographic.geographic_paths import GeographicPaths
from hydromodpy.legacy.geographic.dem_metadata import (
    LegacyDemMetadata,
    read_legacy_dem_metadata,
)
from hydromodpy.legacy.geographic.domain_rasters import (
    LegacyDomainRasterProducts,
    build_legacy_domain_rasters,
)
from hydromodpy.geographic.core.catchment_metrics import compute_catchment_area_km2
from hydromodpy.geographic.core.flow_products import FlowProducts, build_regional_flow_products
from hydromodpy.geographic.core.pipeline_steps import (
    build_standard_catchment,
    build_standard_domain_polygons,
    prepare_geographic_run,
)


@dataclass(frozen=True)
class LegacyGeographicContext:
    """Full legacy geographic payload used to hydrate ``Geographic``."""

    paths: GeographicPaths
    flow_products: FlowProducts
    raster_products: LegacyDomainRasterProducts
    dem_metadata: LegacyDemMetadata
    catchment_area_km2: float
    crs_project: str | None
    epsg: int | None
    dem_res: float

    def legacy_attributes(self) -> dict[str, object]:
        """Return the public legacy attribute payload expected from ``Geographic``."""
        attrs = dict(vars(self.paths))
        attrs.update(
            {
                "catch_area": float(self.catchment_area_km2),
                "crs_proj": self.crs_project,
                "epsg": self.epsg,
                "dem_res": self.dem_res,
                "_paths": self.paths,
                "_dem_metadata": self.dem_metadata,
            }
        )
        attrs.update(self.dem_metadata.legacy_attributes())
        return attrs


def build_legacy_geographic_context(
    *,
    config: GeographicConfig,
    out_dir_path: str | Path,
    backend: WhiteboxBackend | None = None,
    wbt_tool: WhiteboxBackend | None = None,
    locator_factory: object = Nominatim,
) -> LegacyGeographicContext:
    """
    Build the full legacy geographic payload from config + output folder.

    This is the compatibility-oriented counterpart to
    ``build_domain_geographic_context``.
    """
    setup = prepare_geographic_run(
        config=config,
        out_dir_path=out_dir_path,
    )

    if backend is not None and wbt_tool is not None:
        raise ValueError("Pass either 'backend' or legacy alias 'wbt_tool', not both.")
    tool = get_whitebox_backend() if backend is None and wbt_tool is None else (backend or wbt_tool)

    flow_products = build_regional_flow_products(
        dem_init_path=setup.dem_init_path,
        dem_out_dir_path=setup.paths.correcflow_path,
        dem_correc_type=str(config.dem_correc_type),
        crs_project=setup.crs_project,
        backend=tool,
    )

    build_standard_catchment(
        config=config,
        paths=setup.paths,
        direc_path=flow_products.direc,
        acc_path=flow_products.acc,
        crs_project=setup.crs_project,
        backend=tool,
        unsupported_mode="ignore",
    )

    tool.polygons_to_lines(setup.paths.watershed_shp, setup.paths.watershed_contour_shp)
    catchment_area_km2 = float(compute_catchment_area_km2(setup.paths.watershed_shp))

    domain_products = build_standard_domain_polygons(
        config=config,
        paths=setup.paths,
        dem_init_path=setup.dem_init_path,
        crs_project=setup.crs_project,
    )

    raster_products = build_legacy_domain_rasters(
        dem_init_path=setup.dem_init_path,
        correc_path=flow_products.correc,
        direc_path=flow_products.direc,
        watershed_shp=setup.paths.watershed_shp,
        watershed_buff_shp=domain_products.watershed_buff_shp,
        paths=setup.paths,
        crs_project=setup.crs_project,
        backend=tool,
    )

    dem_metadata = read_legacy_dem_metadata(
        watershed_box_buff_dem_path=raster_products.watershed_box_buff_dem,
        watershed_buff_dem_path=raster_products.watershed_buff_dem,
        watershed_dem_path=raster_products.watershed_dem,
        crs_project=setup.crs_project,
        locator_factory=locator_factory,
    )

    return LegacyGeographicContext(
        paths=setup.paths,
        flow_products=flow_products,
        raster_products=raster_products,
        dem_metadata=dem_metadata,
        catchment_area_km2=catchment_area_km2,
        crs_project=setup.crs_project,
        epsg=setup.epsg,
        dem_res=setup.dem_res,
    )

