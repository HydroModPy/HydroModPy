"""Shared orchestration helpers for geographic pipelines.

Purpose
-------
Centralize reusable setup/build steps so both compact and compatibility
pipelines call the same primitives (paths, DEM metadata, catchment extraction,
domain support polygons).

Why this module matters
-----------------------
Keeps orchestration logic explicit and avoids duplicating fragile path/CRS
handling across multiple runner entry points.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import rasterio

from hydromodpy.core.backends import WhiteboxBackend, get_whitebox_backend
from hydromodpy.spatial.geographic.geographic_paths import GeographicPaths, build_geographic_paths
from hydromodpy.spatial.geographic.core.catchment_domain import (
    CatchmentDomainProducts,
    derive_catchment_domain,
)
from hydromodpy.spatial.geographic.core.catchment_from_point import (
    CatchmentFromPointProducts,
    extract_catchment_from_point,
)
from hydromodpy.spatial.geographic.core.catchment_from_polygon import extract_catchment_from_polygon
from hydromodpy.core.tools import toolbox

if TYPE_CHECKING:
    from hydromodpy.spatial.geographic.geographic_config import GeographicConfig


@dataclass(frozen=True)
class PreparedGeographicRun:
    """Canonical shared setup computed before geographic product generation."""

    paths: GeographicPaths
    dem_init_path: str
    crs_project: str | None
    epsg: int | None
    dem_res: float


def _normalize_buff_area(buff_area: float | str | None) -> float | str:
    """Normalize buffer control while preserving support for explicit-distance strings."""
    if buff_area is None:
        raise ValueError("geographic.buff_area is required")
    if isinstance(buff_area, str):
        return buff_area
    return float(buff_area)


def prepare_geographic_run(
    *,
    config: GeographicConfig,
    out_dir_path: str | Path,
) -> PreparedGeographicRun:
    """Build canonical paths, ensure folders exist, and resolve DEM/CRS primitives."""
    if config.dem_init_path is None:
        raise ValueError("geographic.dem_init_path is required")

    paths = build_geographic_paths(out_dir_path)
    toolbox.create_folder(paths.geographic_path)
    toolbox.create_folder(paths.correcflow_path)

    dem_init_path = str(config.dem_init_path)
    with rasterio.open(dem_init_path) as dem_src:
        epsg = dem_src.crs.to_epsg() if dem_src.crs is not None else None
        dem_res = float(abs(dem_src.transform.a))
    crs_project = config.crs_project if config.crs_project is not None else (
        f"EPSG:{epsg}" if epsg is not None else None
    )

    return PreparedGeographicRun(
        paths=paths,
        dem_init_path=dem_init_path,
        crs_project=crs_project,
        epsg=epsg,
        dem_res=dem_res,
    )


def build_standard_catchment(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
    direc_path: str | Path,
    acc_path: str | Path,
    direc_data: object | None = None,
    acc_data: object | None = None,
    crs_project: str | None,
    backend: WhiteboxBackend | None = None,
    unsupported_mode: str = "error",
) -> CatchmentFromPointProducts | str | None:
    """Build the canonical watershed geometry from outlet or polygon config."""
    tool = get_whitebox_backend() if backend is None else backend

    if config.catch_def == "from_outlet_coord":
        if config.x_outlet is None or config.y_outlet is None or config.snap_dist is None:
            raise ValueError(
                "catch_def='from_outlet_coord' requires x_outlet, y_outlet and snap_dist"
            )
        return extract_catchment_from_point(
            x_outlet=float(config.x_outlet),
            y_outlet=float(config.y_outlet),
            snap_dist=int(config.snap_dist),
            acc_path=acc_path,
            direc_path=direc_path,
            acc_data=acc_data,
            direc_data=direc_data,
            output_dir=paths.geographic_path,
            crs_project=crs_project,
            outlet_name="outlet.shp",
            outlet_snap_name="outlet_snap.shp",
            watershed_tif_name=Path(paths.watershed).name,
            watershed_shp_name=Path(paths.watershed_shp).name,
            backend=tool,
        )

    if config.catch_def == "from_polyg_shp":
        if config.polyg_shp_path is None:
            raise ValueError("catch_def='from_polyg_shp' requires polyg_shp_path")
        return extract_catchment_from_polygon(
            polyg_shp_path=config.polyg_shp_path,
            output_shp_path=paths.watershed_shp,
            crs_project=crs_project,
        )

    if unsupported_mode == "ignore":
        return None

    raise ValueError(
        f"Unsupported catch_def for geographic pipeline: {config.catch_def!r}. "
        "Supported values: 'from_outlet_coord', 'from_polyg_shp'."
    )


def build_standard_domain_polygons(
    *,
    config: GeographicConfig,
    paths: GeographicPaths,
    dem_init_path: str | Path,
    crs_project: str | None,
) -> CatchmentDomainProducts:
    """Build buffered catchment, box and box-buffer polygons with canonical names."""
    return derive_catchment_domain(
        catchment_shp=paths.watershed_shp,
        output_dir=paths.geographic_path,
        buff_area=_normalize_buff_area(config.buff_area),
        dem_init_path=dem_init_path,
        crs_project=crs_project,
        watershed_buff_name="watershed_buff.shp",
        watershed_box_name=Path(paths.watershed_box_shp).name,
        watershed_box_buff_name=Path(paths.box_buff).name,
    )

