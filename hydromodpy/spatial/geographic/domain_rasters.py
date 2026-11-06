"""Build geographic raster artifacts on the canonical watershed support."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rasterio

from hydromodpy.core.io.crs import ensure_crs
from hydromodpy.core.io.raster_io import export_tif
from hydromodpy.spatial.delineation.registry import (
    backend_has_callables,
    resolve_delineation_backend,
)
from hydromodpy.spatial.geographic.core.domain_dem import clip_dem_to_box_buffer
from hydromodpy.spatial.geographic.geographic_paths import GeographicPaths


@dataclass(frozen=True)
class DomainRasterProducts:
    """Raster bundle produced on the watershed support.

    The fields are file paths for the box-buffer, watershed-buffer, and
    watershed-only DEM, corrected DEM, D8 direction raster, and watershed
    contour raster. Names intentionally match the established artifacts consumed
    by solver and post-processing code.
    """

    watershed_box_buff_dem: str
    watershed_box_buff_fill: str
    watershed_box_buff_direc: str
    watershed_buff_dem: str
    watershed_buff_fill: str
    watershed_buff_direc: str
    watershed_dem: str
    watershed_fill: str
    watershed_direc: str
    watershed_contour_tif: str


def _clip_raster(
    *,
    src: str | Path,
    polygon: str | Path,
    dst: str | Path,
    maintain_dimensions: bool,
    crs_project: str | None,
    nodata: float | None,
    backend: object,
) -> None:
    """Clip one raster and enforce CRS / nodata conventions."""
    dst_path = str(dst)
    backend.raster.clip_raster_to_polygon(
        str(src),
        str(polygon),
        dst_path,
        maintain_dimensions=maintain_dimensions,
    )
    ensure_crs(dst_path, crs_project)
    if nodata is not None:
        backend.raster.modify_no_data_value(dst_path, new_value=float(nodata))


def _export_reshaped_rasters(
    *,
    paths: GeographicPaths,
) -> None:
    """Re-export watershed rasters on the box-buffer grid when shapes diverge."""
    jobs = [
        (paths.watershed_box_buff_dem, paths.watershed_dem, -9999),
        (paths.watershed_box_buff_fill, paths.watershed_fill, -9999),
        (paths.watershed_box_buff_direc, paths.watershed_direc, -32768),
        (paths.watershed_box_buff_dem, paths.watershed_buff_dem, -9999),
        (paths.watershed_box_buff_fill, paths.watershed_buff_fill, -9999),
        (paths.watershed_box_buff_direc, paths.watershed_buff_direc, -32768),
    ]
    for src_path, dst_path, nodata in jobs:
        with rasterio.open(src_path) as src:
            data = src.read(1)
        export_tif(paths.watershed_box_buff_dem, data, dst_path, nodata)


_DOMAIN_CLIPS = (
    # (raster to clip, polygon, output, keep the dimensions of the raster, nodata of the output)
    ("correc", "box_buff", "watershed_box_buff_fill", False, None),
    ("direc", "box_buff", "watershed_box_buff_direc", False, None),
    ("box_buff_dem", "watershed_buff", "watershed_buff_dem", True, -9999),
    ("correc", "watershed_buff", "watershed_buff_fill", False, None),
    ("direc", "watershed_buff", "watershed_buff_direc", False, None),
    ("box_buff_dem", "watershed", "watershed_dem", True, None),
    ("correc", "watershed", "watershed_fill", False, None),
    ("direc", "watershed", "watershed_direc", False, None),
)


def _clip_jobs(
    paths: GeographicPaths,
    *,
    correc_path: str | Path,
    direc_path: str | Path,
    watershed_shp: str | Path,
    watershed_buff_shp: str | Path,
) -> list[tuple[Path | str, Path | str, Path | str, bool, int | None]]:
    """Return the clips that cut the regional products down to the watershed."""
    rasters = {
        "correc": correc_path,
        "direc": direc_path,
        "box_buff_dem": paths.watershed_box_buff_dem,
    }
    polygons = {
        "box_buff": paths.box_buff,
        "watershed_buff": watershed_buff_shp,
        "watershed": watershed_shp,
    }
    return [
        (rasters[src], polygons[polygon], getattr(paths, dst), keep, nodata)
        for src, polygon, dst, keep, nodata in _DOMAIN_CLIPS
    ]


def _clip_in_memory(
    tool: Any,
    *,
    dem_init_path: str | Path,
    jobs: list[tuple[Path | str, Path | str, Path | str, bool, int | None]],
    watershed_shp: str | Path,
    watershed_buff_shp: str | Path,
    correc_path: str | Path,
    direc_path: str | Path,
    paths: GeographicPaths,
    crs_project: str | None,
) -> None:
    """Clip with a backend that keeps rasters in memory between two clips."""
    dem_init_raster = tool.raster.read_raster(str(dem_init_path))
    correc_raster = tool.raster.read_raster(str(correc_path))
    direc_raster = tool.raster.read_raster(str(direc_path))
    box_buff_vector = tool.raster.read_vector(str(paths.box_buff))
    watershed_buff_vector = tool.raster.read_vector(str(watershed_buff_shp))
    watershed_vector = tool.raster.read_vector(str(watershed_shp))

    watershed_box_buff_dem = tool.raster.clip_raster_to_polygon_raster(
        dem_init_raster,
        box_buff_vector,
        maintain_dimensions=False,
    )
    watershed_box_buff_dem = tool.raster.modify_no_data_value_raster(
        watershed_box_buff_dem,
        new_value=-9999.0,
    )
    tool.raster.write_raster(watershed_box_buff_dem, str(paths.watershed_box_buff_dem))
    ensure_crs(paths.watershed_box_buff_dem, crs_project)

    raster_sources: dict[str, object] = {
        str(correc_path): correc_raster,
        str(direc_path): direc_raster,
        str(paths.watershed_box_buff_dem): watershed_box_buff_dem,
    }
    polygon_sources: dict[str, object] = {
        str(paths.box_buff): box_buff_vector,
        str(watershed_buff_shp): watershed_buff_vector,
        str(watershed_shp): watershed_vector,
    }
    for src, polygon, dst, maintain_dimensions, nodata in jobs:
        clipped = tool.raster.clip_raster_to_polygon_raster(
            raster_sources[str(src)],
            polygon_sources[str(polygon)],
            maintain_dimensions=maintain_dimensions,
        )
        if nodata is not None:
            clipped = tool.raster.modify_no_data_value_raster(clipped, new_value=float(nodata))
        tool.raster.write_raster(clipped, str(dst))
        ensure_crs(dst, crs_project)
        raster_sources[str(dst)] = clipped
    tool.raster.write_raster(
        tool.raster.vector_lines_to_raster_vector(
            watershed_vector,
            base_raster=raster_sources[str(paths.watershed_dem)],
        ),
        str(paths.watershed_contour_tif),
    )


def _clip_through_files(
    tool: Any,
    *,
    dem_init_path: str | Path,
    jobs: list[tuple[Path | str, Path | str, Path | str, bool, int | None]],
    watershed_shp: str | Path,
    paths: GeographicPaths,
    crs_project: str | None,
) -> None:
    """Clip with a backend that reads and writes a file at each step."""
    clip_dem_to_box_buffer(
        dem_init_path=dem_init_path,
        box_buff_shp=paths.box_buff,
        output_dem_path=paths.watershed_box_buff_dem,
        crs_project=crs_project,
        nodata=-9999.0,
        backend=tool,
    )
    for src, polygon, dst, maintain_dimensions, nodata in jobs:
        _clip_raster(
            src=src,
            polygon=polygon,
            dst=dst,
            maintain_dimensions=maintain_dimensions,
            crs_project=crs_project,
            nodata=nodata,
            backend=tool,
        )
    tool.raster.vector_lines_to_raster(
        str(watershed_shp),
        str(paths.watershed_contour_tif),
        base=str(paths.watershed_dem),
    )


def build_domain_rasters(
    *,
    dem_init_path: str | Path,
    correc_path: str | Path,
    direc_path: str | Path,
    watershed_shp: str | Path,
    watershed_buff_shp: str | Path,
    paths: GeographicPaths,
    crs_project: str | None = None,
    backend: object | None = None,
) -> DomainRasterProducts:
    """Build the raster bundle consumed by solvers and post-processing.

    Inputs are the regional DEM/flow products, watershed polygons, and
    canonical geographic paths. Outputs preserve historical filenames, CRS
    handling, and nodata conventions so existing MODFLOW and reporting code can
    consume the artifacts unchanged.
    """
    tool = resolve_delineation_backend(backend)
    jobs = _clip_jobs(
        paths,
        correc_path=correc_path,
        direc_path=direc_path,
        watershed_shp=watershed_shp,
        watershed_buff_shp=watershed_buff_shp,
    )
    if backend_has_callables(
        tool,
        "raster",
        "read_raster",
        "read_vector",
        "clip_raster_to_polygon_raster",
        "modify_no_data_value_raster",
        "write_raster",
        "vector_lines_to_raster_vector",
    ):
        _clip_in_memory(
            tool,
            dem_init_path=dem_init_path,
            jobs=jobs,
            watershed_shp=watershed_shp,
            watershed_buff_shp=watershed_buff_shp,
            correc_path=correc_path,
            direc_path=direc_path,
            paths=paths,
            crs_project=crs_project,
        )
    else:
        _clip_through_files(
            tool,
            dem_init_path=dem_init_path,
            jobs=jobs,
            watershed_shp=watershed_shp,
            paths=paths,
            crs_project=crs_project,
        )
    ensure_crs(paths.watershed_contour_tif, crs_project)

    with (
        rasterio.open(paths.watershed_box_buff_dem) as src1,
        rasterio.open(paths.watershed_buff_dem) as src2,
        rasterio.open(paths.watershed_dem) as src3,
    ):
        s1, s2, s3 = src1.read(1).shape, src2.read(1).shape, src3.read(1).shape
        if not (s1 == s2 == s3):
            _export_reshaped_rasters(paths=paths)

    return DomainRasterProducts(
        watershed_box_buff_dem=paths.watershed_box_buff_dem,
        watershed_box_buff_fill=paths.watershed_box_buff_fill,
        watershed_box_buff_direc=paths.watershed_box_buff_direc,
        watershed_buff_dem=paths.watershed_buff_dem,
        watershed_buff_fill=paths.watershed_buff_fill,
        watershed_buff_direc=paths.watershed_buff_direc,
        watershed_dem=paths.watershed_dem,
        watershed_fill=paths.watershed_fill,
        watershed_direc=paths.watershed_direc,
        watershed_contour_tif=paths.watershed_contour_tif,
    )
