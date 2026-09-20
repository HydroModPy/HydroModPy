"""Copy sealed regional flow products into a child geographic workspace."""

from __future__ import annotations

import shutil
from pathlib import Path

from hydromodpy.spatial.geographic.core.flow_products import (
    FlowProducts,
    flow_products_from_paths,
)
from hydromodpy.spatial.geographic.geographic_config import GeographicConfig
from hydromodpy.spatial.geographic.regional_flow_job import load_regional_flow_job


def copy_regional_flow_from_job(
    *,
    config: GeographicConfig,
    routing_dem_path: str | Path,
    output_dir: str | Path,
    crs_project: str | None,
    backend: object | None = None,
) -> FlowProducts:
    """Verify a regional job, then give one child its own flow rasters."""
    if config.reg_fold is None:
        raise ValueError("geographic.reg_fold is required")
    if config.enforce_lakes.enabled or config.enforce_streams.enabled:
        raise ValueError("Outlet-dependent routing cannot use a shared regional flow job")
    if config.river_network.enabled:
        raise ValueError("River network products cannot use a shared regional flow job")
    job = load_regional_flow_job(
        job_dir=config.reg_fold,
        dem_init_path=routing_dem_path,
        dem_correc_type=config.dem_correc_type,
        crs_project=crs_project,
        engine_id=config.terrain_engine,
        backend=backend,
    )
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    for source in (job.products.correc, job.products.direc, job.products.acc):
        source_path = Path(source)
        shutil.copy2(source_path, destination / source_path.name)
    return flow_products_from_paths(
        dem_out_dir_path=destination,
        dem_correc_type=config.dem_correc_type,
    )
