# -*- coding: utf-8 -*-
"""
Created on Mon Jan 12 09:13:20 2026

@author: pelissierm
"""

from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class GridRasters:
    dem_250m: Path
    cn: Path
    slope: Path
    soil_depth: Path
    hydroprops: Path
    worldcover: Path
    rgi_shp: Path

def run_grid_preprocessing(pgp_module, in_grid: Path, out_grid: Path, rasters: GridRasters,
                           clip_shp: Path | None, out_raster_dir: Path, save_png: bool,
                           logger):

    bundle = pgp_module.RasterBundle(
        dem=rasters.dem_250m,
        cn=rasters.cn,
        slope=rasters.slope,
        depth=rasters.soil_depth,
        hydroprops=rasters.hydroprops,
        worldcover=rasters.worldcover,
    )

    pgp_module.build_grid_from_dem(
        template_csv=in_grid,
        out_csv=out_grid,
        rasters=bundle,
        clip_shp=clip_shp,
        glacier_shp=rasters.rgi_shp,
    )

    logger.info("[grid] preprocessing complete")
    pgp_module.param_grid_stats(out_grid.parent)
    logger.info("[grid] stats extracted")
    
  
